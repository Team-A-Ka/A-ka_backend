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
    "youtube_knowledge_chunk columns",
    "SELECT column_name, data_type, udt_name FROM information_schema.columns "
    "WHERE table_name='youtube_knowledge_chunk' ORDER BY ordinal_position",
)
q("alembic_version", "SELECT version_num FROM alembic_version")
q(
    "all tables",
    "SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name",
)
q("vector ext", "SELECT extname, extversion FROM pg_extension WHERE extname='vector'")
q(
    "indexes on chunk",
    "SELECT indexname FROM pg_indexes WHERE tablename='youtube_knowledge_chunk'",
)
s.close()
