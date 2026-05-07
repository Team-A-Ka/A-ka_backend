"""
[채훈 작업물 — 실패 케이스 테스트]

성공 케이스(test_save_link_only.py)와 별도로 실패 시나리오를 검증.
각 시나리오마다 "기대하는 실패 동작"이 정의되어 있고, 그대로 일어나면 PASS.

실행:
  uv run python test_failure_cases.py        # 전체
  uv run python test_failure_cases.py 1      # 시나리오 1만

요구 환경:
  - .env 의 DATABASE_URL, OPENAI_API_KEY, YOUTUBE_API_KEY
  - PostgreSQL 가동 + alembic upgrade head
  - user(id=1) 시드, category(id=1) 시드
"""
import asyncio
import logging
import sys

logging.basicConfig(
    level=logging.WARNING,  # noise 줄임 (성공 테스트와 다르게)
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)


def banner(title):
    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)


# ======================================================
# 시나리오 1: 잘못된 video_id (존재하지 않는 영상)
# 기대: get_metadata 가 ValueError 또는 HTTPError raise
#       → SaveOnlyService.save 가 그대로 전파
#       → save_link_only_task 가 catch + retry 시도
# ======================================================
def test_scenario_1_invalid_video_id():
    banner("시나리오 1: 잘못된 video_id → 메타 추출 실패")

    from app.services.save_only_service import SaveOnlyService

    fake_id = "INVALID_VIDEO_ID_XX"  # 11자리 짜기엔 부족, 실패 강제
    service = SaveOnlyService()

    try:
        result = service.save(fake_id)
        print(f"❌ 예상과 달리 성공: {result}")
        return False
    except Exception as e:
        print(f"✅ 기대대로 실패: {type(e).__name__}")
        print(f"   메시지: {str(e)[:120]}")
        return True


# ======================================================
# 시나리오 2: Step 2 빈 chunks 가드 동작 검증
# 기대: chunks=[] 입력 시 LangGraph 안 거치고 fallback dict 반환
#       fallback dict 의 title/category 가 미분류, vector_count=0
# ======================================================
def test_scenario_2_empty_chunks_guard():
    banner("시나리오 2: 빈 chunks → 파이프라인 중단 및 에러 발생")

    from app.services.knowledge_pipeline import KnowledgePipelineService

    service = KnowledgePipelineService()
    
    try:
        service.run_intelligence(
            {
                "video_id": "EMPTY_CHUNKS_TEST",
                "chunks": [],          # 핵심
                "metadata": {"video_title": "test"},
            }
        )
        print("❌ 예상과 달리 예외가 발생하지 않고 성공했습니다.")
        return False
    except ValueError as e:
        if "자막 추출 실패" in str(e):
            print(f"✅ 기대대로 ValueError 발생: {e}")
            return True
        else:
            print(f"⚠️ ValueError는 발생했으나 메시지가 다릅니다: {e}")
            return False
    except Exception as e:
        print(f"❌ 기대한 ValueError가 아닌 다른 예외 발생: {type(e).__name__}: {e}")
        return False


# ======================================================
# 시나리오 3: video_id 매칭되는 Knowledge 없을 때 mark_completed 동작
# 기대: best-effort — 경고 로그 + None 반환, raise 안 함
# ======================================================
def test_scenario_3_mark_completed_no_record():
    banner("시나리오 3: 존재하지 않는 video_id 로 mark_completed → best-effort")

    from app.repositories.knowledge import mark_completed

    try:
        result = asyncio.run(mark_completed("NEVER_EXISTED_VIDEO_ID"))
        if result is None:
            print(f"✅ best-effort 동작: None 반환, 경고 로그만")
            return True
        else:
            print(f"⚠️ None 기대했는데 {result} 반환")
            return False
    except Exception as e:
        print(f"❌ raise 발생 (best-effort 위반): {type(e).__name__}: {e}")
        return False


# ======================================================
# 시나리오 4: mark_failed 도 best-effort 검증 (연쇄 실패 방지)
# 기대: 존재하지 않는 video_id 여도 raise 안 함
# ======================================================
def test_scenario_4_mark_failed_best_effort():
    banner("시나리오 4: 존재하지 않는 video_id 로 mark_failed → 연쇄 실패 방지")

    from app.repositories.knowledge import mark_failed

    try:
        result = asyncio.run(
            mark_failed("NEVER_EXISTED_VIDEO_ID", reason="테스트")
        )
        print(f"✅ best-effort 동작: {result} 반환, raise 안 함")
        return True
    except Exception as e:
        print(f"❌ raise 발생 (연쇄 실패 방지 위반): {type(e).__name__}: {e}")
        return False


# ======================================================
# 시나리오 5: 잘못된 user_id 로 save_link_only — FK 위반
# 기대: IntegrityError 가 raise (현재 디자인상 FK 강제)
#       → 호출자가 catch 해야 함
# ======================================================
def test_scenario_5_invalid_user_id_fk():
    banner("시나리오 5: 존재하지 않는 user_id 로 INSERT → FK 위반")

    from app.repositories.knowledge import save_link_only

    fake_metadata = {
        "video_id": "FK_TEST_VID",
        "video_title": "fk test",
        "channel_name": "fk",
        "duration": 1000,
    }

    try:
        # 의도적으로 존재하지 않는 user_id 전달
        asyncio.run(save_link_only("FK_TEST_VID", fake_metadata, user_id=999999))
        print(f"❌ 예상과 달리 INSERT 성공 (user_id=999999 가 실제 존재?)")
        return False
    except Exception as e:
        # asyncpg IntegrityError 를 SQLAlchemy 가 wrap
        msg = str(e)
        if "ForeignKey" in msg or "foreign key" in msg or "참조키" in msg:
            print(f"✅ FK 위반 감지: {type(e).__name__}")
            return True
        else:
            print(f"⚠️ raise 됐지만 FK 관련 아님: {type(e).__name__}: {msg[:100]}")
            return False


# ======================================================
# 시나리오 6: SAVE_ONLY 같은 video_id 두 번 호출 → 중복 INSERT (현재 동작 기록)
# 현재 디자인: UNIQUE constraint 없음 → 중복 row 생김
# 향후 H-3 작업으로 막을 예정. 현재 상태를 명시적으로 기록.
# ======================================================
def test_scenario_6_duplicate_save_only():
    banner("시나리오 6: 같은 video_id 두 번 SAVE_ONLY → 현재는 중복 허용 (기록용)")

    from app.repositories.knowledge import save_link_only

    metadata = {
        "video_id": "DUP_TEST_VID",
        "video_title": "duplicate test",
        "channel_name": "dup",
        "duration": 1000,
    }

    try:
        kid1 = asyncio.run(save_link_only("DUP_TEST_VID", metadata))
        kid2 = asyncio.run(save_link_only("DUP_TEST_VID", metadata))
    except Exception as e:
        print(f"❌ INSERT 자체가 실패: {e}")
        return False

    if kid1 != kid2:
        print(f"⚠️ 중복 row 생성됨 (현재 디자인의 한계)")
        print(f"   1차 knowledge_id: {kid1}")
        print(f"   2차 knowledge_id: {kid2}")
        print(f"   → 향후 작업 H-3 (중복 INSERT 방지) 필요")
        return True  # 현재 동작 기록이 목적이라 PASS 처리
    else:
        print(f"❌ 같은 ID 반환 — upsert 동작?")
        return False


# ======================================================
# 시나리오 7: 잘못된 video_id 로 update_knowledge_after_langgraph
# 기대: Knowledge 못 찾아서 raise (best-effort 아님 — 진짜 실패라고 봄)
# ======================================================
def test_scenario_7_update_no_knowledge():
    banner("시나리오 7: 존재하지 않는 video_id 로 LangGraph 결과 UPDATE")

    from app.repositories.knowledge import update_knowledge_after_langgraph

    try:
        asyncio.run(
            update_knowledge_after_langgraph(
                video_id="NEVER_EXISTED_VID",
                title="x",
                summary="y",
                summarized_chunks=[],
            )
        )
        print(f"❌ 예상과 달리 성공")
        return False
    except Exception as e:
        msg = str(e)
        if "Knowledge 레코드가 없습니다" in msg:
            print(f"✅ 기대대로 실패 — 명확한 에러 메시지")
            print(f"   {msg[:120]}")
            return True
        else:
            print(f"⚠️ raise 됐지만 메시지 다름: {msg[:120]}")
            return False


# ======================================================
# 메인 — 시나리오 선택 실행
# ======================================================
SCENARIOS = {
    "1": ("invalid_video_id", test_scenario_1_invalid_video_id),
    "2": ("empty_chunks_guard", test_scenario_2_empty_chunks_guard),
    "3": ("mark_completed_no_record", test_scenario_3_mark_completed_no_record),
    "4": ("mark_failed_best_effort", test_scenario_4_mark_failed_best_effort),
    "5": ("invalid_user_id_fk", test_scenario_5_invalid_user_id_fk),
    "6": ("duplicate_save_only", test_scenario_6_duplicate_save_only),
    "7": ("update_no_knowledge", test_scenario_7_update_no_knowledge),
}


if __name__ == "__main__":
    selected = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = {}

    for key, (name, fn) in SCENARIOS.items():
        if selected != "all" and selected != key:
            continue
        try:
            results[name] = fn()
        except Exception as e:
            print(f"❌ 시나리오 {key} 자체가 예외: {type(e).__name__}: {e}")
            results[name] = False

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    for name, ok in results.items():
        print(f"  {name:30s}: {'✅ PASS' if ok else '❌ FAIL'}")
    print("=" * 60)

    sys.exit(0 if all(results.values()) else 1)
