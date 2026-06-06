import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine

with engine.connect() as c:
    print("=== per-video ===")
    rows = c.execute(text(
        """
        SELECT m.video_id, k.title, cat.name AS category, k.status,
               COUNT(ch.id) AS chunks,
               COUNT(ch.embedding) AS embedded
          FROM knowledge k
          JOIN youtube_metadata m ON m.knowledge_id = k.id
          LEFT JOIN category cat ON cat.id = k.category_id
          LEFT JOIN youtube_knowledge_chunk ch ON ch.knowledge_id = k.id
         GROUP BY m.video_id, k.title, cat.name, k.status
         ORDER BY chunks
        """
    )).fetchall()
    for r in rows:
        print(f"  {r[0]:14} | {str(r[2]):8} | {r[3]:9} | {r[4]:3} chunks / {r[5]:3} emb | {(r[1] or '')[:34]}")
    print("=== totals ===")
    print("  chunks:", c.execute(text("SELECT COUNT(*) FROM youtube_knowledge_chunk")).scalar(),
          "embedded:", c.execute(text("SELECT COUNT(embedding) FROM youtube_knowledge_chunk")).scalar())
    print("=== categories ===")
    for r in c.execute(text("SELECT id, name FROM category ORDER BY id")):
        print("  ", tuple(r))
