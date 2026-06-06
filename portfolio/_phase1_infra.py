import sys
sys.path.insert(0, ".")

try:
    import redis
    print("redis:", redis.Redis(host="127.0.0.1", port=6379, db=0).ping())
except Exception as e:
    print("redis: FAIL", repr(e))

try:
    from database import SessionLocal
    from sqlalchemy import text
    s = SessionLocal()
    print("knowledge:", s.execute(text("SELECT COUNT(*) FROM knowledge")).scalar())
    print("chunks:", s.execute(text("SELECT COUNT(*) FROM youtube_knowledge_chunk")).scalar())
    print("metadata:", s.execute(text("SELECT COUNT(*) FROM youtube_metadata")).scalar())
    rows = s.execute(
        text("SELECT video_id, video_title FROM youtube_metadata ORDER BY video_id")
    ).fetchall()
    for r in rows:
        print("  video:", r[0], "|", (r[1] or "")[:50])
    s.close()
except Exception as e:
    print("db: FAIL", repr(e))

try:
    from app.core.celery_app import celery_app
    print("celery:", celery_app.control.inspect(timeout=3).ping())
except Exception as e:
    print("celery: FAIL", repr(e))
