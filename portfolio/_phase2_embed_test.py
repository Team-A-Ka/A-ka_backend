import sys, time
sys.path.insert(0, ".")
from app.core.llm import embed_query, embed_texts

# single query
for attempt in range(1, 4):
    try:
        v = embed_query("물티슈 성분이 안전한가요?")
        print(f"[query attempt {attempt}] OK dim={len(v)} head={v[:3]}")
        break
    except Exception as e:
        print(f"[query attempt {attempt}] FAIL {type(e).__name__}: {str(e)[:200]}")
        time.sleep(5)

# small batch (3 texts)
try:
    vs = embed_texts(["가", "나", "다"])
    print(f"[batch3] OK count={len(vs)} dim={len(vs[0])}")
except Exception as e:
    print(f"[batch3] FAIL {type(e).__name__}: {str(e)[:200]}")
