"""Phase 1: build aka_db schema the same way deploy.yml does (create_all),
since the squashed_baseline alembic migration double-creates enums on a clean DB."""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import Base, engine
import app.models  # noqa: F401  register all models on Base.metadata

with engine.begin() as conn:
    conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))

Base.metadata.create_all(bind=engine)

with engine.connect() as conn:
    print("=== tables ===")
    for r in conn.execute(text(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name"
    )):
        print("  ", r[0])
    print("=== embedding column ===")
    for r in conn.execute(text(
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_name='youtube_knowledge_chunk' AND column_name='embedding'"
    )):
        print("  ", tuple(r))
    print("=== chunk indexes ===")
    for r in conn.execute(text(
        "SELECT indexname FROM pg_indexes WHERE tablename='youtube_knowledge_chunk'"
    )):
        print("  ", r[0])
    print("=== vector ext ===")
    for r in conn.execute(text("SELECT extname, extversion FROM pg_extension WHERE extname='vector'")):
        print("  ", tuple(r))
print("DONE")
