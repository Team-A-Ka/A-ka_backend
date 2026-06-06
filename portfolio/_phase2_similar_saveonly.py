import sys, time
from datetime import datetime, timezone
sys.path.insert(0, ".")
from sqlalchemy import text
from database import SessionLocal, engine
from app.services.search_service import find_similar_videos, SIMILAR_DISTANCE_THRESHOLD
from app.services.save_only_service import SaveOnlyService

USER_ID = 21
print(f"SIMILAR_DISTANCE_THRESHOLD = {SIMILAR_DISTANCE_THRESHOLD}")

# ---- load corpus (video_id, knowledge_id, summary, category) ----
s = SessionLocal()
rows = s.execute(text(
    """
    SELECT m.video_id, k.id::text, k.title, k.summary, c.name
      FROM knowledge k
      JOIN youtube_metadata m ON m.knowledge_id = k.id
      LEFT JOIN category c ON c.id = k.category_id
     WHERE k.user_id = :uid
     ORDER BY m.video_id
    """
), {"uid": USER_ID}).fetchall()
s.close()
vids = [{"video_id": r[0], "kid": r[1], "title": r[2], "summary": r[3], "cat": r[4]} for r in rows]

print("\n========== FIND_SIMILAR ==========")
for v in vids:
    res = find_similar_videos(USER_ID, v["summary"] or v["title"], v["kid"])
    print(f"\n[기준] {v['video_id']} ({v['cat']}) {v['title'][:30]}")
    print(f"  -> 유사 {len(res)}개:")
    self_hit = False
    seen_titles = []
    for item in res:
        print(f"     - {item['title'][:40]} | {item['original_url']}")
        seen_titles.append(item['title'])
        if v["title"] == item["title"]:
            self_hit = True
    print(f"  self-excluded: {not self_hit} | dedup(고유 영상수=={len(set(seen_titles))}/{len(seen_titles)}): {len(set(seen_titles))==len(seen_titles)}")

print("\n========== SAVE_ONLY (user_id=1, LLM 0회 검증) ==========")
# LangSmith run count before
since = datetime.now(timezone.utc)
SAVE_USER = 1
SAVE_VID = "o58i-LcqxVE"
# clean any prior save_only by user 1 for idempotency
with engine.begin() as conn:
    conn.execute(text(
        "DELETE FROM youtube_metadata WHERE knowledge_id IN "
        "(SELECT id FROM knowledge WHERE user_id=:u AND original_url LIKE :p)"
    ), {"u": SAVE_USER, "p": f"%{SAVE_VID}%"})
    conn.execute(text(
        "DELETE FROM knowledge WHERE user_id=:u AND original_url LIKE :p"
    ), {"u": SAVE_USER, "p": f"%{SAVE_VID}%"})

res = SaveOnlyService().save(SAVE_VID, SAVE_USER, category_name="과학")
print("save result:", {k: res[k] for k in ("video_id", "knowledge_id", "title", "status")})

# verify: no chunks, summary is link-only
with engine.connect() as conn:
    kid = res["knowledge_id"]
    chunks = conn.execute(text(
        "SELECT COUNT(*) FROM youtube_knowledge_chunk WHERE knowledge_id=CAST(:k AS uuid)"
    ), {"k": kid}).scalar()
    summ = conn.execute(text("SELECT summary FROM knowledge WHERE id=CAST(:k AS uuid)"), {"k": kid}).scalar()
print(f"chunks for save_only knowledge: {chunks} (기대 0)")
print(f"summary: {summ!r}")

# LangSmith: any LLM runs since save start?
time.sleep(6)
try:
    from langsmith import Client
    from app.core.config import settings
    runs = list(Client().list_runs(project_name=settings.LANGCHAIN_PROJECT, start_time=since))
    llm_runs = [r for r in runs if (r.run_type or "") == "llm"]
    print(f"LangSmith LLM runs since save start: {len(llm_runs)} (기대 0)")
except Exception as e:
    print("langsmith check skipped:", e)
