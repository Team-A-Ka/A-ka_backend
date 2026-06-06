"""Celery errback(213bf23) 시그니처 회귀 + 실패경로 검증.
handle_pipeline_failure_task(self, exc, traceback, video_id, user_id) 를
Celery .apply()로 호출 → TypeError 없이 status=FAILED 마킹되는지 확인.
user 21은 notion 연결이 없어 이메일은 recipient=None으로 미발송(안전).
"""
import sys, uuid
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine
from app.tasks.knowledge_tasks import handle_pipeline_failure_task

USER_ID = 21
VID = "FAILTEST123"

# 1. PENDING 레코드 생성 (mark_failed가 video_id로 찾을 수 있게 metadata도)
with engine.begin() as conn:
    conn.execute(text("DELETE FROM youtube_metadata WHERE video_id=:v"), {"v": VID})
    conn.execute(text("DELETE FROM knowledge WHERE original_url LIKE :p"), {"p": f"%{VID}%"})
    kid = uuid.uuid4()
    conn.execute(text(
        "INSERT INTO knowledge (id,user_id,source_type,title,original_url,status,hit_count,created_at,updated_at) "
        "VALUES (:id,:u,'YOUTUBE','errback test',:url,'PENDING',1,now(),now())"
    ), {"id": kid, "u": USER_ID, "url": f"https://www.youtube.com/watch?v={VID}"})
    conn.execute(text(
        "INSERT INTO youtube_metadata (id,knowledge_id,video_id,video_title,channel_name,duration,created_at,updated_at) "
        "VALUES (:id,:kid,:v,'errback test','test',1000,now(),now())"
    ), {"id": uuid.uuid4(), "kid": kid, "v": VID})

print("created PENDING knowledge:", kid)

# 2. Celery 방식으로 errback 호출 (exc, traceback, video_id, user_id)
exc = RuntimeError("forced pipeline failure (errback regression test)")
fake_tb = "Traceback (most recent call last):\n  ...forced...\nRuntimeError: forced"
try:
    result = handle_pipeline_failure_task.apply(args=[exc, fake_tb, VID, USER_ID])
    print("errback invoked, no TypeError. eager state:", result.state)
    print("return value:", result.result)
    sig_ok = True
except TypeError as e:
    print("TypeError (213bf23 REGRESSION!):", e)
    sig_ok = False

# 3. status 확인
with engine.connect() as conn:
    st = conn.execute(text(
        "SELECT k.status FROM knowledge k JOIN youtube_metadata m ON m.knowledge_id=k.id WHERE m.video_id=:v"
    ), {"v": VID}).scalar()
print("knowledge status after errback:", st)
print("PASS errback:", sig_ok and str(st).endswith("FAILED"))
