"""Manual E2E test for Notion hit_count saving and sorted view.

Set DEFAULT_USER and DEFAULT_URL below, then run from the repository root while
the API server, Celery worker, Redis, and DB are running:

    python manual_notion_hit_count_e2e.py

You can still override them from the command line:

    python manual_notion_hit_count_e2e.py --user external_user_test_3 --url https://www.youtube.com/watch?v=VIDEO_ID

The script checks:
1. Local login works.
2. The user has a ready Notion connection.
3. The first summarize request reaches COMPLETED, or the video already exists.
4. On the first run for a video, hit_count is 1.
   On every subsequent run, one duplicate request is sent and hit_count is
   asserted to be +1. Pass --no-check-duplicate to skip the duplicate request.
5. The Notion data source has the hit_count property and sorted view.
6. A Notion row for the source URL appears with the expected hit_count.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import settings  # noqa: E402
from app.services.notion_service import NotionService  # noqa: E402

SOURCE_URL_PROPERTY = "\uc6d0\ubcf8 URL"
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")

# Fill these in if you want to run this file without command-line arguments.
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_USER = "suwang_test_1"
DEFAULT_URL = "https://www.youtube.com/watch?v=uZuVgr-z3bE"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Notion hit_count duplicate-save E2E flow."
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="FastAPI base URL.",
    )
    parser.add_argument(
        "--user",
        default=DEFAULT_USER,
        help="Local login user_name that already has a ready Notion connection.",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help="YouTube URL to test.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=420,
        help="Seconds to wait for the first pipeline completion.",
    )
    parser.add_argument(
        "--poll-interval",
        type=int,
        default=5,
        help="Seconds between DB polling attempts.",
    )
    parser.add_argument(
        "--notion-timeout",
        type=int,
        default=90,
        help="Seconds to wait for Notion row consistency.",
    )
    parser.add_argument(
        "--skip-notion-api",
        action="store_true",
        help="Skip direct Notion API schema, view, and row verification.",
    )
    duplicate_group = parser.add_mutually_exclusive_group()
    duplicate_group.add_argument(
        "--check-duplicate",
        dest="check_duplicate",
        action="store_true",
        default=True,
        help=(
            "Send one duplicate summarize request and assert hit_count increments "
            "by 1 (default on subsequent runs)."
        ),
    )
    duplicate_group.add_argument(
        "--no-check-duplicate",
        dest="check_duplicate",
        action="store_false",
        help="Skip the duplicate summarize request and only verify the current state.",
    )
    args = parser.parse_args()
    if not args.user:
        parser.error("Set DEFAULT_USER in the file or pass --user.")
    if not args.url:
        parser.error("Set DEFAULT_URL in the file or pass --url.")
    return args


def sync_database_url() -> str:
    return settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


def extract_youtube_video_id(youtube_url: str) -> str:
    value = youtube_url.strip()
    if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(value):
        return value

    parsed = urlparse(value)
    query_video_id = parse_qs(parsed.query).get("v", [""])[0]
    if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(query_video_id):
        return query_video_id

    for path_part in reversed([part for part in parsed.path.split("/") if part]):
        if YOUTUBE_VIDEO_ID_PATTERN.fullmatch(path_part):
            return path_part

    raise RuntimeError(f"Could not extract a YouTube video id from: {youtube_url}")


def request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    response = requests.request(
        method,
        url,
        headers=headers,
        json=json,
        timeout=timeout,
    )
    if response.ok:
        return response.json()

    try:
        detail = response.json()
    except ValueError:
        detail = response.text
    raise RuntimeError(f"{method} {url} failed: {response.status_code} {detail}")


def login(base_url: str, user_name: str) -> tuple[dict[str, str], int]:
    body = request_json(
        "POST",
        f"{base_url}/api/v1/auth/login/local",
        json={"user_name": user_name},
    )
    user_id = int(body["user"]["id"])
    token = body["access_token"]
    print(f"[ok] logged in user_id={user_id}")
    return {"Authorization": f"Bearer {token}"}, user_id


def require_ready_notion(base_url: str, headers: dict[str, str]) -> dict[str, Any]:
    notion = request_json("GET", f"{base_url}/api/v1/notion/me", headers=headers)
    if not notion.get("connected") or not notion.get("ready"):
        raise RuntimeError(
            "Notion is not ready for this user. Connect Notion and select a parent "
            "page first."
        )
    print(
        "[ok] notion ready "
        f"database={notion.get('summary_database_id')} "
        f"data_source={notion.get('summary_data_source_id')}"
    )
    return notion


def summarize(
    base_url: str,
    headers: dict[str, str],
    youtube_url: str,
) -> dict[str, Any]:
    response = request_json(
        "POST",
        f"{base_url}/api/v1/youtube/summarize",
        headers=headers,
        json={"url": youtube_url},
        timeout=150,
    )
    print(
        "[ok] summarize "
        f"status={response.get('status')} "
        f"video_id={response.get('video_id')} "
        f"hit_count={response.get('hit_count')} "
        f"duplicate={response.get('duplicate')} "
        f"task_id={response.get('task_id')}"
    )
    return response


def latest_knowledge(engine, user_id: int, video_id: str) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    k.id::text AS knowledge_id,
                    k.status::text AS status,
                    k.hit_count AS hit_count,
                    k.title AS title,
                    k.updated_at AS updated_at
                FROM knowledge k
                JOIN youtube_metadata ym ON ym.knowledge_id = k.id
                WHERE k.user_id = :user_id AND ym.video_id = :video_id
                ORDER BY k.created_at DESC
                LIMIT 1
                """
            ),
            {"user_id": user_id, "video_id": video_id},
        ).mappings().fetchone()

    return dict(row) if row else None


def wait_for_completed(
    engine,
    user_id: int,
    video_id: str,
    *,
    timeout: int,
    poll_interval: int,
) -> dict[str, Any]:
    print(f"[wait] polling DB until video_id={video_id} is COMPLETED")
    deadline = time.time() + timeout
    last_status = None

    while time.time() < deadline:
        row = latest_knowledge(engine, user_id, video_id)
        if row:
            last_status = row["status"]
            if last_status == "COMPLETED":
                print(
                    "[ok] pipeline completed "
                    f"knowledge_id={row['knowledge_id']} hit_count={row['hit_count']}"
                )
                return row
            if last_status == "FAILED":
                raise RuntimeError(f"pipeline failed for video_id={video_id}")

        print(f"[wait] status={last_status or 'missing'}")
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Timed out after {timeout}s waiting for video_id={video_id}; "
        f"last_status={last_status}"
    )


def notion_connection(engine, user_id: int) -> dict[str, Any]:
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT
                    access_token,
                    summary_database_id,
                    summary_data_source_id
                FROM notion_connection
                WHERE user_id = :user_id
                LIMIT 1
                """
            ),
            {"user_id": user_id},
        ).mappings().fetchone()

    if not row:
        raise RuntimeError(f"No notion_connection row for user_id={user_id}")
    return dict(row)


def notion_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Notion-Version": settings.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(
    method: str,
    path: str,
    *,
    access_token: str,
    json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return request_json(
        method,
        f"{NotionService.base_url}{path}",
        headers=notion_headers(access_token),
        json=json,
    )


def verify_notion_schema_and_view(connection: dict[str, Any]) -> None:
    access_token = connection["access_token"]
    database_id = connection["summary_database_id"]
    data_source_id = connection["summary_data_source_id"]
    if not database_id or not data_source_id:
        raise RuntimeError("Notion summary database/data source ids are missing.")

    data_source = notion_request(
        "GET",
        f"/data_sources/{data_source_id}",
        access_token=access_token,
    )
    hit_count_property = (data_source.get("properties") or {}).get(
        NotionService.summary_hit_count_property
    )
    if not hit_count_property or hit_count_property.get("type") != "number":
        raise AssertionError("Notion data source is missing the hit_count number field.")
    print("[ok] notion data source has hit_count number property")
    hit_count_sort_properties = {NotionService.summary_hit_count_property}
    hit_count_property_id = hit_count_property.get("id")
    if hit_count_property_id:
        hit_count_sort_properties.add(hit_count_property_id)

    views = notion_request(
        "GET",
        f"/views?database_id={database_id}",
        access_token=access_token,
    ).get("results", [])

    for view_ref in views:
        view = notion_request("GET", f"/views/{view_ref['id']}", access_token=access_token)
        if view.get("name") != NotionService.summary_hit_count_view_name:
            continue
        if not is_hit_count_descending_sort(
            view.get("sorts"),
            hit_count_sort_properties,
        ):
            raise AssertionError(f"Hit-count view has unexpected sorts: {view.get('sorts')}")
        print("[ok] notion hit_count sorted view exists")
        return

    raise AssertionError("Notion hit_count sorted view was not found.")


def is_hit_count_descending_sort(
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


def query_notion_rows(
    connection: dict[str, Any],
    *,
    page_size: int = 100,
) -> list[dict[str, Any]]:
    payload = {
        "page_size": page_size,
        "sorts": [
            {
                "property": NotionService.summary_hit_count_property,
                "direction": "descending",
            }
        ],
    }
    response = notion_request(
        "POST",
        f"/data_sources/{connection['summary_data_source_id']}/query",
        access_token=connection["access_token"],
        json=payload,
    )
    return response.get("results", [])


def page_property(page: dict[str, Any], property_name: str) -> dict[str, Any]:
    value = (page.get("properties") or {}).get(property_name)
    return value if isinstance(value, dict) else {}


def verify_notion_row(
    connection: dict[str, Any],
    *,
    source_url: str,
    expected_hit_count: int,
    timeout: int,
) -> None:
    print("[wait] querying Notion rows for expected hit_count")
    deadline = time.time() + timeout

    while time.time() < deadline:
        rows = query_notion_rows(connection)
        hit_counts = [
            page_property(row, NotionService.summary_hit_count_property).get("number")
            for row in rows
        ]
        if hit_counts != sorted(hit_counts, reverse=True):
            raise AssertionError(f"Notion query was not sorted descending: {hit_counts}")

        matching_rows = [
            row
            for row in rows
            if page_property(row, SOURCE_URL_PROPERTY).get("url") == source_url
        ]
        if len(matching_rows) > 1:
            raise AssertionError(
                f"Expected one Notion row for url={source_url}, "
                f"found {len(matching_rows)}"
            )

        for row in matching_rows:
            hit_count = page_property(row, NotionService.summary_hit_count_property).get(
                "number"
            )
            if hit_count == expected_hit_count:
                print(
                    "[ok] notion row found "
                    f"url={source_url} hit_count={expected_hit_count}"
                )
                return

        print(f"[wait] latest notion hit_counts={hit_counts}")
        time.sleep(3)

    raise TimeoutError(
        f"Timed out waiting for Notion row url={source_url} "
        f"hit_count={expected_hit_count}"
    )


def run() -> None:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    engine = create_engine(sync_database_url(), pool_pre_ping=True)

    headers, user_id = login(base_url, args.user)
    require_ready_notion(base_url, headers)

    video_id = extract_youtube_video_id(args.url)
    before_duplicate = latest_knowledge(engine, user_id, video_id)
    record_just_created = before_duplicate is None

    if before_duplicate is None:
        first_response = summarize(base_url, headers, args.url)
        if first_response["video_id"] != video_id:
            raise AssertionError(
                f"Expected video_id={video_id}, got {first_response['video_id']}"
            )
        if first_response.get("status") != "QUEUED":
            raise AssertionError(
                "Expected first request to queue a new pipeline, got "
                f"{first_response}"
            )
        before_duplicate = wait_for_completed(
            engine,
            user_id,
            video_id,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )
    elif before_duplicate["status"] != "COMPLETED":
        before_duplicate = wait_for_completed(
            engine,
            user_id,
            video_id,
            timeout=args.timeout,
            poll_interval=args.poll_interval,
        )

    current_hit_count = int(before_duplicate["hit_count"] or 0)
    expected_hit_count = current_hit_count
    print(f"[ok] current hit_count={current_hit_count}")

    # Increment only on subsequent runs. The very first run already produced
    # hit_count=1 by creating the record, so don't double-bump it.
    should_check_duplicate = args.check_duplicate and not record_just_created

    if should_check_duplicate:
        duplicate_response = summarize(base_url, headers, args.url)
        if not duplicate_response.get("duplicate"):
            raise AssertionError(f"Expected duplicate response, got {duplicate_response}")
        if duplicate_response.get("status") != "duplicate_hit_count_updated_in_notion":
            raise AssertionError(
                "Expected duplicate_hit_count_updated_in_notion, got "
                f"{duplicate_response.get('status')}"
            )

        expected_hit_count = current_hit_count + 1
        actual_hit_count = int(duplicate_response["hit_count"])
        if actual_hit_count != expected_hit_count:
            raise AssertionError(
                f"Expected hit_count={expected_hit_count}, got {actual_hit_count}"
            )
        print(f"[ok] duplicate response hit_count={actual_hit_count}")

        after_duplicate = latest_knowledge(engine, user_id, video_id)
        if not after_duplicate or int(after_duplicate["hit_count"]) != expected_hit_count:
            raise AssertionError(f"DB hit_count was not updated: {after_duplicate}")
        print("[ok] DB hit_count matches duplicate response")
    elif record_just_created:
        print("[ok] first run for this video; skipping duplicate request")
    else:
        print("[ok] duplicate check skipped; hit_count was not incremented")

    require_ready_notion(base_url, headers)
    if not args.skip_notion_api:
        connection = notion_connection(engine, user_id)
        verify_notion_schema_and_view(connection)
        verify_notion_row(
            connection,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            expected_hit_count=expected_hit_count,
            timeout=args.notion_timeout,
        )

    print("\nPASS: Notion hit_count E2E flow succeeded.")


if __name__ == "__main__":
    run()
