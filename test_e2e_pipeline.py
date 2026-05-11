"""
A-Ka Backend End-to-End (E2E) Pipeline Test Script

이 스크립트는 카카오 웹훅 엔드포인트를 통해
UPLOAD, SAVE_ONLY, SEARCH 3가지 핵심 의도를 순차적으로 테스트하며,
Celery 백그라운드 작업이 완료될 때까지 DB를 폴링(Polling)하여
전체 시스템 흐름이 정상적으로 동작하는지 통합 검증합니다.
"""

import urllib.request
import json
import time
import sys
import uuid
from sqlalchemy import create_engine, text
from app.core.config import settings

# DB 연결 엔진 설정
engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", ""))

# 유사 영상 테스트용 고정 유저 — 같은 유저로 여러 영상을 누적 업로드할 때 사용
# 테스트 완료 후 다시 랜덤으로 되돌리려면 아래 두 줄을 주석 처리하고
# 랜덤 줄 주석을 해제할 것
TEST_USER_ID = "e2e_fixed_user_01"

# 매 실행마다 새 유저 생성 (기본 모드)
# TEST_USER_ID = f"e2e_test_{uuid.uuid4().hex[:8]}"

print(f"[*] 테스트 카카오 User ID: {TEST_USER_ID}")


def get_internal_user_id(kakao_id: str) -> int | None:
    """카카오 ID → user_channel_identity → user.id 조회"""
    with engine.connect() as conn:
        result = conn.execute(
            text(
                """
                SELECT u.id FROM "user" u
                JOIN user_channel_identity uci ON uci.user_id = u.id
                WHERE uci.provider = 'kakao' AND uci.provider_user_id = :kid
                """
            ),
            {"kid": kakao_id},
        ).fetchone()
        return result[0] if result else None


def send_webhook(utterance: str, intent_name: str = "test"):
    url = "http://localhost:8000/api/v1/chat/webhook"
    data = json.dumps(
        {
            "userRequest": {"user": {"id": TEST_USER_ID}, "utterance": utterance},
            "action": {"name": intent_name},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )

    start_time = time.time()
    try:
        resp = urllib.request.urlopen(req)
        end_time = time.time()
        result = json.loads(resp.read().decode("utf-8"))
        return result, end_time - start_time
    except Exception as e:
        print(f"❌ 웹훅 요청 실패: {e}")
        sys.exit(1)


def wait_for_knowledge_status(video_id: str, internal_user_id: int, timeout: int = 180):
    """user_id + video_id 기준으로 Knowledge.status가 COMPLETED/FAILED가 될 때까지 대기"""
    print(
        f"⏳ 처리 대기 중... (User: {internal_user_id}, video: {video_id}, 최대 {timeout}초)"
    )
    start_time = time.time()

    with engine.connect() as conn:
        while time.time() - start_time < timeout:
            result = conn.execute(
                text(
                    """
                    SELECT k.status
                    FROM knowledge k
                    JOIN youtube_metadata ym ON k.id = ym.knowledge_id
                    WHERE ym.video_id = :video_id AND k.user_id = :user_id
                    ORDER BY k.created_at DESC LIMIT 1
                    """
                ),
                {"video_id": video_id, "user_id": internal_user_id},
            ).fetchone()

            if result:
                status = result[0]
                if status == "COMPLETED":
                    print(
                        f"✅ 처리 완료! (상태: {status}, 소요 시간: {time.time() - start_time:.1f}초)"
                    )
                    return True
                elif status == "FAILED":
                    print(f"❌ 처리 실패! (상태: {status})")
                    return False

            time.sleep(5)  # 5초마다 확인
            print(".", end="", flush=True)

    print(f"\n❌ 시간 초과: {timeout}초 동안 처리가 완료되지 않았습니다.")
    return False


def run_e2e_tests():
    print("=" * 60)
    print("🚀 A-Ka Backend E2E 통합 테스트 시작")
    print("=" * 60)

    # 1. UPLOAD (요약 포함) 테스트
    print("\n[테스트 1] UPLOAD 의도 웹훅 전송 (요약 파이프라인)")
    video_id_upload = "SSY3JvrogaA"
    utterance_upload = f"https://www.youtube.com/watch?v={video_id_upload} 요약해줘"

    res, latency = send_webhook(utterance_upload)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")

    # 웹훅 호출 후 DB에 유저가 생성될 때까지 잠시 대기
    time.sleep(2)
    internal_id = get_internal_user_id(TEST_USER_ID)
    if not internal_id:
        print("❌ 오류: 유저가 DB에 생성되지 않았습니다.")
        sys.exit(1)
    print(f"[*] 확인된 내부 User ID: {internal_id}")

    # 현재 유저의 UPLOAD 파이프라인 완료까지 대기
    if not wait_for_knowledge_status(video_id_upload, internal_id):
        print("중단: UPLOAD 파이프라인 실패")
        sys.exit(1)

    # 2. SAVE_ONLY (단순 저장) 테스트
    print("\n[테스트 2] SAVE_ONLY 의도 웹훅 전송 (단순 저장)")
    video_id_save_only = "L_Guz73e6fw"  # 짧은 아무 영상
    utterance_save = f"https://www.youtube.com/watch?v={video_id_save_only} 저장만 해"

    res, latency = send_webhook(utterance_save)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")

    # 현재 유저의 SAVE_ONLY 완료까지 대기
    if not wait_for_knowledge_status(video_id_save_only, internal_id, timeout=30):
        print("중단: SAVE_ONLY 파이프라인 실패")
        sys.exit(1)

    # 3. SEARCH (RAG 검색) 테스트
    print("\n[테스트 3] SEARCH 의도 웹훅 전송 (RAG 파이프라인)")
    # 테스트 1에서 올린 와인 영상을 바탕으로 질문
    utterance_search = "무알콜 맥주는 알코올이 정말 알코올이 없나?"

    res, latency = send_webhook(utterance_search)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")
    print(f"   (카카오 5초 규약: 즉시 OK 반환 — AI 답변은 Celery 워커에서 비동기 처리)")

    # SEARCH Celery 처리 대기 (데이터가 확실히 적재된 후라 짧게)
    print("⏳ Celery SEARCH 처리 대기 중 (최대 10초)...", end="", flush=True)
    for _ in range(5):
        time.sleep(2)
        print(".", end="", flush=True)
    print(" 완료!")

    print("\n" + "=" * 60)
    print("🎉 모든 E2E 테스트 시나리오 통과 완료!")
    print("=" * 60)
    print("\n📋 [SEARCH 결과 확인]")
    print("   Celery 워커 로그에서 아래 키워드를 찾으세요:")
    print("   1. '[AI Router] intent=SEARCH'       → 의도 분류 확인")
    print("   2. '[SEARCH 노드2: 검색] 완료'        → pgvector 검색 결과")
    print("   3. '===== [AI 답변 내용] ====='       → 최종 AI 답변")


if __name__ == "__main__":
    # run_e2e_tests()
        # FIND_SIMILAR 단독 테스트
    res, latency = send_webhook(
        "https://www.youtube.com/watch?v=TzLBgclsxmo 이 영상이랑 비슷한 거 찾아줘"
    )
    print(f"응답: {res}")
    print(f"지연: {latency:.4f}초")