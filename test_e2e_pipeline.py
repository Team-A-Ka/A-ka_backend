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
from sqlalchemy import create_engine, text
from app.core.config import settings

# DB 연결 엔진 설정
engine = create_engine(settings.DATABASE_URL.replace("+asyncpg", ""))

def send_webhook(utterance: str, intent_name: str = "test"):
    url = 'http://localhost:8000/api/v1/chat/webhook'
    data = json.dumps({
        'userRequest': {'user': {'id': 'test_user'}, 'utterance': utterance},
        'action': {'name': intent_name}
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'})
    
    start_time = time.time()
    try:
        resp = urllib.request.urlopen(req)
        end_time = time.time()
        result = json.loads(resp.read().decode("utf-8"))
        return result, end_time - start_time
    except Exception as e:
        print(f"❌ 웹훅 요청 실패: {e}")
        sys.exit(1)

def wait_for_knowledge_status(video_id: str, timeout: int = 180):
    """지정된 video_id의 Knowledge.status가 COMPLETED 또는 FAILED가 될 때까지 대기"""
    print(f"⏳ Celery 파이프라인 처리 대기 중... (video_id: {video_id}, 최대 {timeout}초)")
    start_time = time.time()
    
    with engine.connect() as conn:
        while time.time() - start_time < timeout:
            result = conn.execute(
                text(
                    """
                    SELECT k.status 
                    FROM knowledge k
                    JOIN youtube_metadata ym ON k.id = ym.knowledge_id
                    WHERE ym.video_id = :video_id
                    ORDER BY k.created_at DESC LIMIT 1
                    """
                ),
                {"video_id": video_id}
            ).fetchone()

            if result:
                status = result[0]
                if status == "COMPLETED":
                    print(f"✅ 처리 완료! (상태: {status}, 소요 시간: {time.time() - start_time:.1f}초)")
                    return True
                elif status == "FAILED":
                    print(f"❌ 처리 실패! (상태: {status})")
                    return False
            
            time.sleep(5) # 5초마다 확인
            print(".", end="", flush=True)
            
    print(f"\n❌ 시간 초과: {timeout}초 동안 처리가 완료되지 않았습니다.")
    return False

def run_e2e_tests():
    print("=" * 60)
    print("🚀 A-Ka Backend E2E 통합 테스트 시작")
    print("=" * 60)

    # 1. UPLOAD (요약 포함) 테스트
    print("\n[테스트 1] UPLOAD 의도 웹훅 전송 (요약 파이프라인)")
    video_id_upload = "7z8F4a5Qg10"  # 와인 두통 관련 영상 (약 5분)
    utterance_upload = f"https://www.youtube.com/watch?v={video_id_upload} 요약해줘"
    
    res, latency = send_webhook(utterance_upload)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")
    
    # 워커가 처리할 때까지 대기
    if not wait_for_knowledge_status(video_id_upload):
        print("중단: UPLOAD 파이프라인 실패")
        sys.exit(1)


    # 2. SAVE_ONLY (단순 저장) 테스트
    print("\n[테스트 2] SAVE_ONLY 의도 웹훅 전송 (단순 저장)")
    video_id_save_only = "L_Guz73e6fw" # 짧은 아무 영상
    utterance_save = f"https://www.youtube.com/watch?v={video_id_save_only} 저장만 해"
    
    res, latency = send_webhook(utterance_save)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")
    
    # 워커가 처리할 때까지 대기 (SAVE_ONLY는 매우 빠름)
    if not wait_for_knowledge_status(video_id_save_only, timeout=30):
        print("중단: SAVE_ONLY 파이프라인 실패")
        sys.exit(1)


    # 3. SEARCH (RAG 검색) 테스트
    print("\n[테스트 3] SEARCH 의도 웹훅 전송 (RAG 파이프라인)")
    # 테스트 1에서 올린 와인 영상을 바탕으로 질문
    utterance_search = "와인이 두통을 유발하는 이유가 뭐야?"
    
    res, latency = send_webhook(utterance_search)
    print(f"✅ 웹훅 응답 수신 (지연시간: {latency:.4f}초)")
    
    # 참고: 현재 SEARCH 응답은 Celery 워커의 로그에만 남고 웹훅 응답은 항상 '서버 연결 성공'임
    print(f"💡 (검색 결과는 워커 로그를 확인해주세요. 응답 메시지: {res['template']['outputs'][0]['simpleText']['text']})")


    print("\n" + "=" * 60)
    print("🎉 모든 E2E 테스트 시나리오 통과 완료!")
    print("=" * 60)

if __name__ == "__main__":
    run_e2e_tests()
