import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine
from app.tasks.knowledge_tasks import run_core_pipeline_task

USER_ID = 21
VID = "o58i-LcqxVE"
URL = f"https://www.youtube.com/watch?v={VID}"


def snap():
    with engine.connect() as c:
        row = c.execute(text(
            """
            SELECT k.hit_count, k.status,
                   (SELECT COUNT(*) FROM youtube_knowledge_chunk ch WHERE ch.knowledge_id=k.id) AS chunks
              FROM knowledge k JOIN youtube_metadata m ON m.knowledge_id=k.id
             WHERE m.video_id=:v AND k.user_id=:u
            """
        ), {"v": VID, "u": USER_ID}).first()
        return tuple(row) if row else None


before = snap()
print("before (hit_count, status, chunks):", before)
res = run_core_pipeline_task(URL, VID, USER_ID, include_similar=False)
print("dispatch result:", {k: res.get(k) for k in ("status", "duplicate", "hit_count")})
after = snap()
print("after  (hit_count, status, chunks):", after)
print("PASS dup:", before and after and after[0] == before[0] + 1 and after[2] == before[2])
