"""
유사 영상 검색 기능 테스트 (test_similar_videos.py)

사전 조건:
  - 동일한 user_id로 저장된 영상이 2개 이상 DB에 있어야 함
  - 영상들에 chunk 임베딩이 저장되어 있어야 함 (UPLOAD 파이프라인 완료 상태)

===========================================================
테스트 설정 (아래 두 값만 수정해서 사용)
===========================================================
"""

# -------------------------------------------------------
# 모드 A: 유튜브 링크 기준 검색 (DB에 이미 저장된 영상이어야 함)
#   → 해당 영상의 summary를 DB에서 꺼내 검색 쿼리로 사용
#   → TEST_QUERY_TEXT는 무시됨
# -------------------------------------------------------
TEST_QUERY_URL = "https://www.youtube.com/watch?v=7z8F4a5Qg10"

# -------------------------------------------------------
# 모드 B: 자연어 텍스트 기준 검색
#   → TEST_QUERY_URL = None 으로 두면 이 텍스트로 검색
# -------------------------------------------------------
TEST_QUERY_TEXT = "알코올 음료가 몸에 미치는 영향"

# 비교에서 제외할 영상 URL
# 모드 A: TEST_QUERY_URL과 같은 영상을 자동 제외하므로 보통 None으로 둬도 됨
# 모드 B: 제외하고 싶은 영상이 있으면 URL 입력, 없으면 None
TEST_EXCLUDE_URL = None

# 테스트할 user_id (None 이면 영상 가장 많은 유저 자동 선택)
TEST_USER_ID = 17

"""
===========================================================
실행:
  uv run python test_similar_videos.py
===========================================================
"""

import re
import sys
from sqlalchemy import create_engine, text
from app.core.config import settings
from app.services.search_service import find_similar_videos, openai_client

engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", ""))


def extract_video_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(
        r"(?:youtube\.com/(?:[^/]+/.+/|(?:v|e(?:mbed)?)/|.*[?&]v=)|youtu\.be/)([^\"&?/\s]{11})",
        url,
    )
    return match.group(1) if match else None


def get_users_with_embeddings() -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT k.user_id,
                       COUNT(DISTINCT k.id) AS video_count,
                       COUNT(kc.id)         AS chunk_count
                FROM knowledge k
                JOIN youtube_knowledge_chunk kc ON kc.knowledge_id = k.id
                WHERE kc.embedding IS NOT NULL
                GROUP BY k.user_id
                ORDER BY video_count DESC
                """
            )
        ).fetchall()
    return [{"user_id": r[0], "video_count": r[1], "chunk_count": r[2]} for r in rows]


def get_knowledge_list(user_id: int) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT k.id, k.title, k.original_url,
                       ym.video_id,
                       COUNT(kc.id) AS chunk_count
                FROM knowledge k
                JOIN youtube_knowledge_chunk kc ON kc.knowledge_id = k.id
                JOIN youtube_metadata ym ON ym.knowledge_id = k.id
                WHERE k.user_id = :uid AND kc.embedding IS NOT NULL
                GROUP BY k.id, k.title, k.original_url, ym.video_id
                ORDER BY k.created_at DESC
                """
            ),
            {"uid": user_id},
        ).fetchall()
    return [
        {
            "knowledge_id": str(r[0]),
            "title": r[1],
            "url": r[2],
            "video_id": r[3],
            "chunk_count": r[4],
        }
        for r in rows
    ]


def get_exclude_knowledge_id(user_id: int, video_id: str) -> str | None:
    """제외할 video_id → knowledge_id 조회 (최신 레코드 기준)"""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT k.id FROM knowledge k
                JOIN youtube_metadata ym ON ym.knowledge_id = k.id
                WHERE k.user_id = :uid AND ym.video_id = :vid
                ORDER BY k.created_at DESC LIMIT 1
                """
            ),
            {"uid": user_id, "vid": video_id},
        ).fetchone()
    return str(row[0]) if row else None


def run_test():
    print("\n========== [유사 영상 검색 테스트] ==========\n")

    # 1. 유저 현황 출력
    users = get_users_with_embeddings()
    if not users:
        print("[FAIL] 임베딩이 있는 영상 데이터가 없습니다. UPLOAD 파이프라인 먼저 실행하세요.")
        return

    print("[DB 현황] 임베딩 보유 유저:")
    for u in users:
        print(f"  user_id={u['user_id']} | 영상 {u['video_count']}개 | 청크 {u['chunk_count']}개")

    # 2. user_id 결정
    user_id = TEST_USER_ID
    if user_id is None:
        target = next((u for u in users if u["video_count"] >= 2), users[0])
        user_id = target["user_id"]
    print(f"\n[*] 테스트 대상 user_id: {user_id}")

    # 3. 보유 영상 목록 출력
    knowledge_list = get_knowledge_list(user_id)
    if not knowledge_list:
        print(f"[FAIL] user_id={user_id}의 임베딩 데이터가 없습니다.")
        return

    print(f"\n[보유 영상 목록] ({len(knowledge_list)}개):")
    for i, k in enumerate(knowledge_list):
        print(f"  [{i+1}] {k['title']} (청크 {k['chunk_count']}개)")

    # 4. 모드 결정: URL 기준 or 자연어 기준
    query_video_id = extract_video_id(TEST_QUERY_URL)

    if query_video_id:
        # 모드 A: URL → DB에서 summary 조회
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    """
                    SELECT k.id, k.title, k.summary
                    FROM knowledge k
                    JOIN youtube_metadata ym ON ym.knowledge_id = k.id
                    WHERE k.user_id = :uid AND ym.video_id = :vid
                      AND k.summary IS NOT NULL AND k.summary != ''
                    ORDER BY k.created_at DESC LIMIT 1
                    """
                ),
                {"uid": user_id, "vid": query_video_id},
            ).fetchone()

        if not row:
            print(f"\n[FAIL] TEST_QUERY_URL의 영상이 DB에 없거나 summary가 없습니다.")
            print(f"       먼저 해당 영상을 UPLOAD 파이프라인으로 처리해주세요.")
            return

        search_query = row[2]
        current_knowledge_id = str(row[0])  # 자기 자신 자동 제외
        print(f"\n[모드 A] URL 기준 검색")
        print(f"  기준 영상: {row[1]}")
        print(f"  summary 길이: {len(search_query)}자 (자동 추출)")
    else:
        # 모드 B: 자연어 텍스트 기준
        search_query = TEST_QUERY_TEXT

        exclude_video_id = extract_video_id(TEST_EXCLUDE_URL)
        exclude_knowledge_id = None
        if exclude_video_id:
            exclude_knowledge_id = get_exclude_knowledge_id(user_id, exclude_video_id)
            if exclude_knowledge_id:
                print(f"\n[제외 영상]: {TEST_EXCLUDE_URL}")
            else:
                print(f"\n[WARN] 제외 영상이 DB에 없습니다. 전체 대상 검색합니다.")

        current_knowledge_id = exclude_knowledge_id or "00000000-0000-0000-0000-000000000000"
        print(f"\n[모드 B] 자연어 기준 검색")

    print(f"\n[검색 쿼리]: \"{search_query[:80]}{'...' if len(search_query) > 80 else ''}\"")

    # 6. 실제 distance 먼저 확인 (threshold 없이 전체 조회)
    print("\n[*] 전체 영상 distance 확인 중 (threshold 없음)...\n")
    resp = openai_client.embeddings.create(
        model="text-embedding-3-small",
        input=search_query,
    )
    query_vector = resp.data[0].embedding
    vector_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT ym.video_id,
                       k.title,
                       MIN(kc.embedding <=> CAST(:query_vec AS vector)) AS min_distance
                FROM youtube_knowledge_chunk kc
                JOIN knowledge k  ON kc.knowledge_id = k.id
                JOIN youtube_metadata ym ON ym.knowledge_id = k.id
                WHERE k.user_id = :uid
                  AND k.id != CAST(:current_kid AS uuid)
                  AND kc.embedding IS NOT NULL
                GROUP BY ym.video_id, k.title
                ORDER BY min_distance
                """
            ),
            {
                "query_vec": vector_str,
                "uid": user_id,
                "current_kid": current_knowledge_id,
            },
        ).fetchall()

    print("[distance 전체 현황]")
    for r in rows:
        flag = "✅" if r[2] < 0.65 else ("🟡" if r[2] < 0.75 else "❌")
        print(f"  {flag} distance={r[2]:.4f} | {r[1]}")
    print()

    # 7. find_similar_videos 호출
    print("[*] find_similar_videos() 호출 중...\n")
    result = find_similar_videos(
        user_id=user_id,
        summary=search_query,
        current_knowledge_id=current_knowledge_id,
    )

    # 8. 결과 출력
    print("\n========== [결과] ==========")
    if not result:
        print("유사 영상 없음 (distance threshold 초과 또는 저장된 영상 부족)")
    else:
        print(f"유사 영상 {len(result)}개 발견:")
        for i, v in enumerate(result, 1):
            print(f"  [{i}] {v['title']}")
            print(f"       {v['url']}")
    print("============================\n")


if __name__ == "__main__":
    run_test()
