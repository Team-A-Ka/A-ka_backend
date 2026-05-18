import base64
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from jwt import InvalidTokenError

from app.core.config import settings


class NotionServiceError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


class NotionService:
    base_url = "https://api.notion.com/v1"
    rich_text_limit = 2000
    oauth_state_type = "notion_oauth_state"
    summary_hit_count_property = "조회수"
    summary_hit_count_view_name = "조회수 높은 순"
    summary_source_url_property = "원본 URL"

    def __init__(self, api_key: str | None = None, notion_version: str | None = None):
        self.api_key = api_key or ""
        self.notion_version = notion_version or settings.NOTION_VERSION

    @property
    def headers(self) -> dict[str, str]:
        if not self.api_key:
            raise NotionServiceError("Notion access token is not configured.", status_code=500)
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Notion-Version": self.notion_version,
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = requests.request(
                method,
                f"{self.base_url}{path}",
                headers=self.headers,
                timeout=15,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise NotionServiceError(f"Failed to call Notion API: {exc}") from exc

        if response.ok:
            return response.json()

        detail = self._extract_error_detail(response)
        raise NotionServiceError(detail, status_code=response.status_code)

    def _oauth_request(self, body: dict[str, Any]) -> dict[str, Any]:
        if not settings.NOTION_OAUTH_CLIENT_ID or not settings.NOTION_OAUTH_CLIENT_SECRET:
            raise NotionServiceError(
                "Notion OAuth client credentials are not configured.",
                status_code=500,
            )

        credential = (
            f"{settings.NOTION_OAUTH_CLIENT_ID}:"
            f"{settings.NOTION_OAUTH_CLIENT_SECRET}"
        )
        encoded = base64.b64encode(credential.encode("utf-8")).decode("ascii")
        headers = {
            "Authorization": f"Basic {encoded}",
            "Notion-Version": self.notion_version,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            response = requests.post(
                f"{self.base_url}/oauth/token",
                headers=headers,
                json=body,
                timeout=15,
            )
        except requests.RequestException as exc:
            raise NotionServiceError(f"Failed to call Notion OAuth API: {exc}") from exc

        if response.ok:
            return response.json()

        detail = self._extract_error_detail(response)
        raise NotionServiceError(detail, status_code=response.status_code)

    @staticmethod
    def _extract_error_detail(response: requests.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text or "Notion API request failed."
        return payload.get("message") or payload.get("code") or "Notion API request failed."

    def get_bot_user(self) -> dict[str, Any]:
        return self._request("GET", "/users/me")

    def retrieve_page(self, page_id: str) -> dict[str, Any]:
        normalized_page_id = self._normalize_page_id(page_id)
        if not normalized_page_id:
            raise NotionServiceError("page_id is required.", status_code=400)
        return self._request("GET", f"/pages/{normalized_page_id}")

    def update_page_properties(
        self,
        page_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_page_id = self._normalize_page_id(page_id)
        if not normalized_page_id:
            raise NotionServiceError("page_id is required.", status_code=400)
        return self._request(
            "PATCH",
            f"/pages/{normalized_page_id}",
            json={"properties": properties},
        )

    def archive_page(self, page_id: str) -> dict[str, Any]:
        normalized_page_id = self._normalize_page_id(page_id)
        if not normalized_page_id:
            raise NotionServiceError("page_id is required.", status_code=400)
        return self._request(
            "PATCH",
            f"/pages/{normalized_page_id}",
            json={"archived": True},
        )

    def build_oauth_authorization_url(self, state: str) -> str:
        if not settings.NOTION_OAUTH_CLIENT_ID:
            raise NotionServiceError(
                "NOTION_OAUTH_CLIENT_ID is not configured.",
                status_code=500,
            )
        if not settings.NOTION_OAUTH_REDIRECT_URI:
            raise NotionServiceError(
                "NOTION_OAUTH_REDIRECT_URI is not configured.",
                status_code=500,
            )

        query = urlencode(
            {
                "owner": "user",
                "client_id": settings.NOTION_OAUTH_CLIENT_ID,
                "redirect_uri": settings.NOTION_OAUTH_REDIRECT_URI,
                "response_type": "code",
                "state": state,
            }
        )
        return f"{settings.NOTION_OAUTH_AUTH_URL}?{query}"

    def create_oauth_state(self, user_id: int) -> str:
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        payload = {
            "sub": str(user_id),
            "type": self.oauth_state_type,
            "nonce": secrets.token_urlsafe(16),
            "exp": expires_at,
        }
        return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

    def decode_oauth_state(self, state: str) -> int:
        try:
            payload = jwt.decode(
                state,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
            )
            if payload.get("type") != self.oauth_state_type:
                raise ValueError("Invalid OAuth state type")
            return int(payload["sub"])
        except (InvalidTokenError, KeyError, TypeError, ValueError) as exc:
            raise NotionServiceError("Invalid Notion OAuth state.", status_code=400) from exc

    def exchange_oauth_code(self, code: str) -> dict[str, Any]:
        return self._oauth_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.NOTION_OAUTH_REDIRECT_URI,
            }
        )

    def refresh_oauth_token(self, refresh_token: str) -> dict[str, Any]:
        return self._oauth_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
            }
        )

    def search(
        self,
        query: str = "",
        object_type: str | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "query": query,
            "page_size": page_size,
            "sort": {"direction": "descending", "timestamp": "last_edited_time"},
        }
        if object_type:
            body["filter"] = {"property": "object", "value": object_type}
        return self._request("POST", "/search", json=body)

    def create_summary_page(
        self,
        title: str,
        summary: str,
        parent_page_id: str,
        source_url: str | None = None,
    ) -> dict[str, Any]:
        parent_id = self._normalize_page_id(parent_page_id)
        if not parent_id:
            raise NotionServiceError(
                "parent_page_id is required.",
                status_code=400,
            )

        body = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "properties": {"title": {"title": self._rich_text(title)}},
            "children": self._summary_blocks(summary, source_url),
        }
        return self._request("POST", "/pages", json=body)

    def create_child_page(
        self,
        title: str,
        parent_page_id: str,
        content: str | None = None,
    ) -> dict[str, Any]:
        parent_id = self._normalize_page_id(parent_page_id)
        if not parent_id:
            raise NotionServiceError(
                "parent_page_id is required.",
                status_code=400,
            )

        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "properties": {"title": {"title": self._rich_text(title)}},
        }
        if content is not None:
            body["children"] = self._summary_blocks(content)

        return self._request("POST", "/pages", json=body)

    def create_workspace_page(
        self,
        title: str,
        content: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "parent": {"type": "workspace", "workspace": True},
            "properties": {"title": {"title": self._rich_text(title)}},
        }
        if content is not None:
            body["children"] = self._summary_blocks(content)

        return self._request("POST", "/pages", json=body)

    def create_summary_database(
        self,
        parent_page_id: str,
        title: str = "A-ka 요약 저장소",
    ) -> dict[str, Any]:
        parent_id = self._normalize_page_id(parent_page_id)
        if not parent_id:
            raise NotionServiceError(
                "parent_page_id is required.",
                status_code=400,
            )

        body: dict[str, Any] = {
            "parent": {"type": "page_id", "page_id": parent_id},
            "title": self._rich_text(title),
            "is_inline": True,
            "initial_data_source": {
                "properties": self._summary_database_properties(),
            },
        }
        return self._request("POST", "/databases", json=body)

    def retrieve_database(
        self,
        database_id: str,
    ) -> dict[str, Any]:
        normalized_database_id = self._normalize_page_id(database_id)
        if not normalized_database_id:
            raise NotionServiceError("database_id is required.", status_code=400)
        return self._request("GET", f"/databases/{normalized_database_id}")

    def retrieve_data_source(
        self,
        data_source_id: str,
    ) -> dict[str, Any]:
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        if not normalized_data_source_id:
            raise NotionServiceError("data_source_id is required.", status_code=400)
        return self._request("GET", f"/data_sources/{normalized_data_source_id}")

    def update_data_source(
        self,
        data_source_id: str,
        properties: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        if not normalized_data_source_id:
            raise NotionServiceError("data_source_id is required.", status_code=400)
        return self._request(
            "PATCH",
            f"/data_sources/{normalized_data_source_id}",
            json={"properties": properties},
        )

    def query_data_source(
        self,
        data_source_id: str,
        *,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, Any]] | None = None,
        page_size: int = 10,
    ) -> dict[str, Any]:
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        if not normalized_data_source_id:
            raise NotionServiceError("data_source_id is required.", status_code=400)

        body: dict[str, Any] = {"page_size": page_size}
        if filter:
            body["filter"] = filter
        if sorts:
            body["sorts"] = sorts

        return self._request(
            "POST",
            f"/data_sources/{normalized_data_source_id}/query",
            json=body,
        )

    def list_views(self, database_id: str) -> dict[str, Any]:
        normalized_database_id = self._normalize_page_id(database_id)
        if not normalized_database_id:
            raise NotionServiceError("database_id is required.", status_code=400)
        query = urlencode({"database_id": normalized_database_id})
        return self._request("GET", f"/views?{query}")

    def retrieve_view(self, view_id: str) -> dict[str, Any]:
        normalized_view_id = self._normalize_page_id(view_id)
        if not normalized_view_id:
            raise NotionServiceError("view_id is required.", status_code=400)
        return self._request("GET", f"/views/{normalized_view_id}")

    def create_view(
        self,
        database_id: str,
        data_source_id: str,
        name: str,
        sorts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_database_id = self._normalize_page_id(database_id)
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        if not normalized_database_id:
            raise NotionServiceError("database_id is required.", status_code=400)
        if not normalized_data_source_id:
            raise NotionServiceError("data_source_id is required.", status_code=400)

        body = {
            "database_id": normalized_database_id,
            "data_source_id": normalized_data_source_id,
            "name": name,
            "type": "table",
            "sorts": sorts,
            "position": {"type": "start"},
        }
        return self._request("POST", "/views", json=body)

    def update_view(
        self,
        view_id: str,
        sorts: list[dict[str, Any]],
    ) -> dict[str, Any]:
        normalized_view_id = self._normalize_page_id(view_id)
        if not normalized_view_id:
            raise NotionServiceError("view_id is required.", status_code=400)
        return self._request(
            "PATCH",
            f"/views/{normalized_view_id}",
            json={"sorts": sorts},
        )

    def ensure_summary_database_schema(self, data_source_id: str) -> dict[str, Any]:
        data_source = self.retrieve_data_source(data_source_id)
        properties = data_source.get("properties") or {}
        hit_count_property = properties.get(self.summary_hit_count_property)
        if (
            isinstance(hit_count_property, dict)
            and hit_count_property.get("type") == "number"
        ):
            return data_source

        return self.update_data_source(
            data_source_id,
            {
                self.summary_hit_count_property: {
                    "number": {"format": "number"}
                }
            },
        )

    def ensure_hit_count_sorted_view(
        self,
        database_id: str,
        data_source_id: str,
    ) -> dict[str, Any]:
        sorts = self._hit_count_descending_sorts()
        views = self.list_views(database_id).get("results", [])
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        sort_property_identifiers: set[str] | None = None

        for view_ref in views:
            if view_ref.get("name") != self.summary_hit_count_view_name:
                continue

            view = view_ref
            if "sorts" not in view or "data_source_id" not in view:
                view = self.retrieve_view(view_ref["id"])

            view_data_source_id = self._normalize_page_id(view.get("data_source_id"))
            if view_data_source_id and view_data_source_id != normalized_data_source_id:
                continue
            if sort_property_identifiers is None:
                sort_property_identifiers = self._hit_count_sort_property_identifiers(
                    data_source_id
                )
            if self._is_hit_count_descending_sorts(
                view.get("sorts"),
                sort_property_identifiers,
            ):
                return view
            return self.update_view(view["id"], sorts)

        return self.create_view(
            database_id=database_id,
            data_source_id=data_source_id,
            name=self.summary_hit_count_view_name,
            sorts=sorts,
        )

    def create_summary_database_item(
        self,
        data_source_id: str,
        title: str,
        summary: str,
        body_summary: str | None = None,
        category: str | None = None,
        source_url: str | None = None,
        saved_at: datetime | None = None,
        hit_count: int | None = 1,
    ) -> dict[str, Any]:
        normalized_data_source_id = self._normalize_page_id(data_source_id)
        if not normalized_data_source_id:
            raise NotionServiceError(
                "data_source_id is required.",
                status_code=400,
            )

        properties: dict[str, Any] = {
            "제목": {"title": self._rich_text(title)},
            "요약": {"rich_text": self._rich_text(summary)},
            "저장일": {
                "date": {
                    "start": (saved_at or datetime.now(timezone.utc)).isoformat()
                }
            },
        }
        if category:
            properties["카테고리"] = {"select": {"name": category[:100]}}
        if source_url:
            properties[self.summary_source_url_property] = {"url": source_url}
        if hit_count is not None:
            properties[self.summary_hit_count_property] = {
                "number": max(int(hit_count), 0)
            }

        body: dict[str, Any] = {
            "parent": {
                "type": "data_source_id",
                "data_source_id": normalized_data_source_id,
            },
            "properties": properties,
            "children": self._summary_blocks(body_summary or summary, source_url),
        }
        return self._request("POST", "/pages", json=body)

    def find_summary_database_item_by_source_url(
        self,
        data_source_id: str,
        source_url: str,
    ) -> dict[str, Any] | None:
        results = self.find_summary_database_items_by_source_url(
            data_source_id,
            source_url,
            page_size=1,
        )
        return results[0] if results else None

    def find_summary_database_items_by_source_url(
        self,
        data_source_id: str,
        source_url: str,
        *,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        response = self.query_data_source(
            data_source_id,
            filter={
                "property": self.summary_source_url_property,
                "url": {"equals": source_url},
            },
            sorts=[
                {
                    "property": self.summary_hit_count_property,
                    "direction": "descending",
                }
            ],
            page_size=page_size,
        )
        results = response.get("results") or []
        return results if isinstance(results, list) else []

    def update_summary_database_item_hit_count(
        self,
        page_id: str,
        hit_count: int,
    ) -> dict[str, Any]:
        return self.update_page_properties(
            page_id,
            {
                self.summary_hit_count_property: {
                    "number": max(int(hit_count), 0)
                }
            },
        )

    @staticmethod
    def extract_data_source_id(database_payload: dict[str, Any]) -> str:
        candidates = [
            database_payload.get("data_sources"),
            database_payload.get("data_source"),
            database_payload.get("initial_data_source"),
        ]

        for candidate in candidates:
            if isinstance(candidate, list) and candidate:
                data_source_id = candidate[0].get("id")
            elif isinstance(candidate, dict):
                data_source_id = candidate.get("id")
            else:
                data_source_id = None

            normalized = NotionService._normalize_page_id(data_source_id)
            if normalized:
                return normalized

        return ""

    @staticmethod
    def _summary_database_properties() -> dict[str, Any]:
        return {
            "제목": {"title": {}},
            "카테고리": {"select": {}},
            "원본 URL": {"url": {}},
            "요약": {"rich_text": {}},
            "저장일": {"date": {}},
            NotionService.summary_hit_count_property: {
                "number": {"format": "number"}
            },
        }

    @staticmethod
    def _hit_count_descending_sorts() -> list[dict[str, str]]:
        return [
            {
                "property": NotionService.summary_hit_count_property,
                "direction": "descending",
            }
        ]

    def _hit_count_sort_property_identifiers(self, data_source_id: str) -> set[str]:
        identifiers = {self.summary_hit_count_property}
        try:
            data_source = self.retrieve_data_source(data_source_id)
        except NotionServiceError:
            return identifiers

        hit_count_property = (data_source.get("properties") or {}).get(
            self.summary_hit_count_property
        )
        if isinstance(hit_count_property, dict):
            property_id = hit_count_property.get("id")
            if property_id:
                identifiers.add(property_id)
        return identifiers

    @staticmethod
    def _is_hit_count_descending_sorts(
        sorts: Any,
        property_identifiers: set[str],
    ) -> bool:
        if not isinstance(sorts, list) or len(sorts) != 1:
            return False

        sort = sorts[0]
        return (
            isinstance(sort, dict)
            and sort.get("direction") == "descending"
            and sort.get("property") in property_identifiers
        )

    def _summary_blocks(
        self,
        summary: str,
        source_url: str | None = None,
    ) -> list[dict[str, Any]]:
        blocks = []
        for paragraph in self._paragraphs(summary):
            blocks.extend(
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": self._rich_text(chunk)},
                }
                for chunk in self._chunk_text(paragraph)
            )
        if source_url:
            blocks.append(
                {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {"url": source_url},
                }
            )
        return blocks

    def _paragraphs(self, text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return [""]
        return [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n+", stripped)
            if paragraph.strip()
        ]

    def _chunk_text(self, text: str) -> list[str]:
        stripped = text.strip()
        if not stripped:
            return [""]
        return [
            stripped[index : index + self.rich_text_limit]
            for index in range(0, len(stripped), self.rich_text_limit)
        ]

    @staticmethod
    def _rich_text(content: str) -> list[dict[str, Any]]:
        return [
            {
                "type": "text",
                "text": {"content": content[: NotionService.rich_text_limit]},
            }
        ]

    @staticmethod
    def _normalize_page_id(page_id: str | None) -> str:
        if not page_id:
            return ""

        cleaned = page_id.strip()
        compact_match = re.search(r"([0-9a-fA-F]{32})", cleaned.replace("-", ""))
        if not compact_match:
            return cleaned

        compact = compact_match.group(1)
        return (
            f"{compact[:8]}-{compact[8:12]}-{compact[12:16]}-"
            f"{compact[16:20]}-{compact[20:]}"
        )
