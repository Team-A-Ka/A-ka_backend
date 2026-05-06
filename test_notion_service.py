from urllib.parse import parse_qs, urlparse

from app.services.notion_service import NotionService, NotionServiceError


class DummyResponse:
    def __init__(self, ok=True, payload=None, status_code=200, text=""):
        self.ok = ok
        self._payload = payload or {}
        self.status_code = status_code
        self.text = text

    def json(self):
        return self._payload


def test_search_sends_notion_headers_and_filter(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "json": kwargs["json"],
            }
        )
        return DummyResponse(payload={"results": []})

    monkeypatch.setattr("app.services.notion_service.requests.request", fake_request)

    service = NotionService(api_key="secret", notion_version="2026-03-11")
    service.search(query="notes", object_type="page", page_size=5)

    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.notion.com/v1/search"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["headers"]["Notion-Version"] == "2026-03-11"
    assert captured["json"]["filter"] == {"property": "object", "value": "page"}


def test_create_summary_page_requires_parent():
    service = NotionService(api_key="secret", notion_version="2026-03-11")

    try:
        service.create_summary_page(title="Title", summary="Summary", parent_page_id="")
    except NotionServiceError as exc:
        assert exc.status_code == 400
        assert "parent_page_id" in str(exc)
    else:
        raise AssertionError("Expected NotionServiceError")


def test_create_summary_page_builds_children(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update({"method": method, "url": url, "json": kwargs["json"]})
        return DummyResponse(payload={"id": "page-id", "url": "https://notion.so/page"})

    monkeypatch.setattr("app.services.notion_service.requests.request", fake_request)

    service = NotionService(api_key="secret", notion_version="2026-03-11")
    page = service.create_summary_page(
        title="My summary",
        summary="Useful notes",
        parent_page_id="parent-id",
        source_url="https://example.com",
    )

    assert page["id"] == "page-id"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.notion.com/v1/pages"
    assert captured["json"]["parent"] == {"type": "page_id", "page_id": "parent-id"}
    title_property = captured["json"]["properties"]["title"]["title"]
    assert title_property[0]["text"]["content"] == "My summary"
    assert captured["json"]["children"][0]["type"] == "paragraph"
    assert captured["json"]["children"][1] == {
        "object": "block",
        "type": "bookmark",
        "bookmark": {"url": "https://example.com"},
    }


def test_create_summary_page_normalizes_compact_page_id(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update({"json": kwargs["json"]})
        return DummyResponse(payload={"id": "page-id"})

    monkeypatch.setattr("app.services.notion_service.requests.request", fake_request)

    service = NotionService(api_key="secret", notion_version="2026-03-11")
    service.create_summary_page(
        title="Title",
        summary="Summary",
        parent_page_id="3501b54ad663800f8e40f1d87631c4ec",
    )

    assert captured["json"]["parent"]["page_id"] == (
        "3501b54a-d663-800f-8e40-f1d87631c4ec"
    )


def test_retrieve_page_normalizes_page_id(monkeypatch):
    captured = {}

    def fake_request(method, url, headers, timeout, **kwargs):
        captured.update({"method": method, "url": url})
        return DummyResponse(payload={"id": "page-id", "object": "page"})

    monkeypatch.setattr("app.services.notion_service.requests.request", fake_request)

    service = NotionService(api_key="secret", notion_version="2026-03-11")
    page = service.retrieve_page("3501b54ad663800f8e40f1d87631c4ec")

    assert page["object"] == "page"
    assert captured["method"] == "GET"
    assert captured["url"] == (
        "https://api.notion.com/v1/pages/"
        "3501b54a-d663-800f-8e40-f1d87631c4ec"
    )


def test_build_oauth_authorization_url(monkeypatch):
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_CLIENT_ID",
        "client-id",
    )
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_REDIRECT_URI",
        "https://example.com/callback",
    )
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_AUTH_URL",
        "https://api.notion.com/v1/oauth/authorize",
    )

    url = NotionService(api_key="secret").build_oauth_authorization_url("state-token")
    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "api.notion.com"
    assert query["owner"] == ["user"]
    assert query["client_id"] == ["client-id"]
    assert query["redirect_uri"] == ["https://example.com/callback"]
    assert query["response_type"] == ["code"]
    assert query["state"] == ["state-token"]


def test_exchange_oauth_code_uses_basic_auth(monkeypatch):
    captured = {}

    def fake_post(url, headers, json, timeout):
        captured.update(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "timeout": timeout,
            }
        )
        return DummyResponse(
            payload={
                "access_token": "access",
                "refresh_token": "refresh",
                "bot_id": "bot-id",
                "workspace_id": "workspace-id",
            }
        )

    monkeypatch.setattr("app.services.notion_service.requests.post", fake_post)
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_CLIENT_ID",
        "client-id",
    )
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_CLIENT_SECRET",
        "client-secret",
    )
    monkeypatch.setattr(
        "app.services.notion_service.settings.NOTION_OAUTH_REDIRECT_URI",
        "https://example.com/callback",
    )

    payload = NotionService(api_key="secret").exchange_oauth_code("code")

    assert payload["access_token"] == "access"
    assert captured["url"] == "https://api.notion.com/v1/oauth/token"
    assert captured["headers"]["Authorization"].startswith("Basic ")
    assert captured["headers"]["Notion-Version"] == "2026-03-11"
    assert captured["json"] == {
        "grant_type": "authorization_code",
        "code": "code",
        "redirect_uri": "https://example.com/callback",
    }
