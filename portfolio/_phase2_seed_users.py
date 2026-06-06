import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine

with engine.begin() as conn:
    for uid, name in [(1, "seed_user"), (21, "kpi_user")]:
        conn.execute(
            text(
                'INSERT INTO "user" (id, user_name, is_active, created_at, updated_at) '
                "VALUES (:id, :name, true, now(), now()) ON CONFLICT (id) DO NOTHING"
            ),
            {"id": uid, "name": name},
        )
    conn.execute(text(
        "SELECT setval(pg_get_serial_sequence('\"user\"','id'), "
        '(SELECT MAX(id) FROM "user"))'
    ))

with engine.connect() as conn:
    for r in conn.execute(text('SELECT id, user_name FROM "user" ORDER BY id')):
        print("user:", tuple(r))
print("DONE")
