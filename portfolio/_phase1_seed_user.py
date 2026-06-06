import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine

with engine.begin() as conn:
    conn.execute(text(
        'INSERT INTO "user" (id, user_name, is_active, created_at, updated_at) '
        "VALUES (1, 'seed_user', true, now(), now()) ON CONFLICT (id) DO NOTHING"
    ))
    conn.execute(text(
        "SELECT setval(pg_get_serial_sequence('\"user\"','id'), "
        'GREATEST((SELECT MAX(id) FROM "user"), 1))'
    ))

with engine.connect() as conn:
    for r in conn.execute(text('SELECT id, user_name, is_active FROM "user" ORDER BY id')):
        print("user:", tuple(r))
print("DONE")
