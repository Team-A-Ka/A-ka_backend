import sys
sys.path.insert(0, ".")
from database import SessionLocal
from sqlalchemy import text

s = SessionLocal()


def q(label, sql):
    try:
        rows = s.execute(text(sql)).fetchall()
        print(f"--- {label} ---")
        for r in rows:
            print("  ", tuple(r))
    except Exception as e:
        s.rollback()
        print(f"--- {label}: FAIL {e!r}")


q(
    "knowledge",
    "SELECT id, user_id, category_id, source_type, status, "
    "(summary IS NOT NULL) AS has_summary, hit_count, original_url, created_at "
    "FROM knowledge ORDER BY created_at",
)
q("metadata", "SELECT knowledge_id, video_id, video_title, duration FROM youtube_metadata")
q("chunks total", "SELECT COUNT(*) AS chunks, COUNT(embedding) AS with_embedding FROM youtube_knowledge_chunk")
q("category", "SELECT id, name FROM category ORDER BY id")
q("user", "SELECT id, user_name FROM \"user\" ORDER BY id")
s.close()
