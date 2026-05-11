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

    def _summary_blocks(
        self,
        summary: str,
        source_url: str | None = None,
    ) -> list[dict[str, Any]]:
        blocks = [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": self._rich_text(chunk)},
            }
            for chunk in self._chunk_text(summary)
        ]
        if source_url:
            blocks.append(
                {
                    "object": "block",
                    "type": "bookmark",
                    "bookmark": {"url": source_url},
                }
            )
        return blocks

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
