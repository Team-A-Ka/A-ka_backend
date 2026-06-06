import sys, json
sys.path.insert(0, ".")
from app.services.search_service import search_and_answer

USER_ID = 21
cases = [
    ("relevant", "물티슈에 들어있는 성분이 안전한가요?"),
    ("absent", "손흥민의 이번 시즌 골 수는?"),
]
for label, q in cases:
    try:
        res = search_and_answer(USER_ID, q)
        ans = res.get("answer") or res.get("reply") or "" if isinstance(res, dict) else str(res)
        srcs = (res.get("sources") or res.get("references") or []) if isinstance(res, dict) else []
        chunks = res.get("chunks") if isinstance(res, dict) else None
        print(f"=== {label} | q={q}")
        print("  answer:", (ans[:220] + "...") if len(ans) > 220 else ans)
        print("  sources:", srcs if not hasattr(srcs, "__len__") else len(srcs), srcs if isinstance(srcs, list) else "")
        print("  chunks_used:", len(chunks) if chunks is not None else "n/a")
    except Exception as e:
        print(f"=== {label} | FAIL {type(e).__name__}: {str(e)[:200]}")
