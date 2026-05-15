"""Manual helper for the first Notion OAuth connection.

Fill DEFAULT_USER below, then run while the FastAPI server is running:

    python manual_notion_connect.py

The script logs in with the local test user, creates the Notion OAuth URL, opens
it in your browser, and polls /api/v1/notion/me until the connection is ready.
"""

from __future__ import annotations

import argparse
import http.client
import json
import time
from typing import Any
from urllib.parse import parse_qs, urlparse


# Fill this in if you want to run this file without command-line arguments.
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_USER = "suwang_test_1"
DEFAULT_OPEN_BROWSER = True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Connect a local user to Notion.")
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="FastAPI base URL.",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help="Local login user_name to connect with Notion.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Print the OAuth URL without opening a browser.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=180,
        help="Seconds to wait for the OAuth callback to complete.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=3,
        help="Seconds between /notion/me polling attempts.",
    )

    args = parser.parse_args()
    if not args.user:
        parser.error("Set DEFAULT_USER in the file or pass --user.")
    return args


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    data = None
    if json is not None:
        data = json_dumps(json).encode("utf-8")

    request_headers = dict(headers or {})
    if data is not None:
        request_headers["Content-Type"] = "application/json"

    scheme, host, port, path = split_url(url)
    connection_cls = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    connection = connection_cls(host, port=port, timeout=timeout)
    try:
        connection.request(method, path, body=data, headers=request_headers)
        response = connection.getresponse()
        raw = response.read()
        if 200 <= response.status < 300:
            return json_loads(raw)

        detail = json_loads(raw)
        raise RuntimeError(f"{method} {url} failed: {response.status} {detail}")
    finally:
        connection.close()


def split_url(url: str) -> tuple[str, str, int | None, str]:
    if "://" not in url:
        raise ValueError(f"Invalid URL: {url}")

    scheme, rest = url.split("://", 1)
    host_port, _, path = rest.partition("/")
    host, port = split_host_port(host_port, scheme)
    return scheme, host, port, "/" + path


def split_host_port(host_port: str, scheme: str) -> tuple[str, int | None]:
    if ":" not in host_port:
        return host_port, 443 if scheme == "https" else 80

    host, port_text = host_port.rsplit(":", 1)
    return host, int(port_text)


def json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def json_loads(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"raw": raw.decode("utf-8", errors="replace")}
    return value if isinstance(value, dict) else {"value": value}


def login(base_url: str, user_name: str) -> dict[str, str]:
    body = request_json(
        "POST",
        f"{base_url}/api/v1/auth/login/local",
        json={"user_name": user_name},
    )
    user = body["user"]
    print(f"[ok] logged in user_id={user['id']} user_name={user.get('user_name')}")
    return {"Authorization": f"Bearer {body['access_token']}"}


def create_oauth_url(base_url: str, headers: dict[str, str]) -> str:
    body = request_json(
        "GET",
        f"{base_url}/api/v1/notion/oauth/start",
        headers=headers,
    )
    authorization_url = body["authorization_url"]
    validate_oauth_redirect_uri(authorization_url)
    print("\nNotion OAuth URL:")
    print(authorization_url)
    return authorization_url


def validate_oauth_redirect_uri(authorization_url: str) -> None:
    parsed = urlparse(authorization_url)
    redirect_uri = parse_qs(parsed.query).get("redirect_uri", [""])[0]
    if redirect_uri.startswith("https://"):
        return

    raise RuntimeError(
        "Notion OAuth redirect_uri must be HTTPS for this integration.\n"
        f"Current redirect_uri: {redirect_uri or '(missing)'}\n"
        "Create an HTTPS tunnel, then set NOTION_OAUTH_REDIRECT_URI to:\n"
        "  https://YOUR-TUNNEL/api/v1/notion/oauth/callback\n"
        "Register the exact same URL in the Notion developer dashboard and "
        "restart FastAPI."
    )


def get_notion_status(base_url: str, headers: dict[str, str]) -> dict[str, Any]:
    return request_json("GET", f"{base_url}/api/v1/notion/me", headers=headers)


def wait_until_ready(
    base_url: str,
    headers: dict[str, str],
    *,
    timeout: int,
    poll_interval: int,
) -> dict[str, Any]:
    print("\n[wait] approve the Notion OAuth request in your browser")
    deadline = time.time() + timeout
    last_status: dict[str, Any] | None = None

    while time.time() < deadline:
        last_status = get_notion_status(base_url, headers)
        if last_status.get("connected") and last_status.get("ready"):
            print("[ok] Notion connection is ready")
            return last_status

        print(
            "[wait] "
            f"connected={last_status.get('connected')} "
            f"ready={last_status.get('ready')} "
            f"parent_page_id={last_status.get('parent_page_id')}"
        )
        time.sleep(poll_interval)

    raise TimeoutError(f"Timed out waiting for Notion connection: {last_status}")


def run() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    headers = login(base_url, args.user)
    authorization_url = create_oauth_url(base_url, headers)

    if DEFAULT_OPEN_BROWSER and not args.no_open:
        import webbrowser

        opened = webbrowser.open(authorization_url)
        if opened:
            print("[ok] browser opened")
        else:
            print("[warn] could not open browser automatically; paste the URL manually")
    else:
        print("\nOpen the URL above in your browser.")

    status = wait_until_ready(
        base_url,
        headers,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
    )
    print("\nConnection:")
    print(f"  workspace_id: {status.get('workspace_id')}")
    print(f"  workspace_name: {status.get('workspace_name')}")
    print(f"  parent_page_id: {status.get('parent_page_id')}")
    print(f"  summary_database_id: {status.get('summary_database_id')}")
    print(f"  summary_data_source_id: {status.get('summary_data_source_id')}")
    print("\nPASS: Notion connection completed.")


if __name__ == "__main__":
    run()
