import sys
sys.path.insert(0, ".")
from database import SessionLocal
from sqlalchemy import text
from app.core.config import settings

s = SessionLocal()
print("config DATABASE_URL host/db:", str(settings.database_url).split("@")[-1])
print("current_database:", s.execute(text("SELECT current_database()")).scalar())
print("--- databases on server ---")
for r in s.execute(text("SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY datname")).fetchall():
    print("  ", r[0])
s.close()
