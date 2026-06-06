"""SEARCH RAG 스모크: 시드 영상에 대한 질의 1~3개 발사하고 답변·지연시간 보고."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.search_service import search_and_answer

USER_ID = 21
QUERIES = [
    "물티슈에 들어있는 소듐 벤조에이트가 위험해?",
    "물티슈 성분 중에 어떤 게 논란이 됐어?",
    "화장품에 쓰는 보존제는 뭐가 있나",
]

for i, q in enumerate(QUERIES, 1):
    print(f"\n{'='*60}\nQ{i}: {q}\n{'='*60}")
    t0 = time.time()
    try:
        res = search_and_answer(USER_ID, q)
        dt = time.time() - t0
        # search_and_answer returns dict with answer/refs/etc — shape unknown, dump key bits
        if isinstance(res, dict):
            ans = res.get("answer") or res.get("reply") or res.get("text") or ""
            refs = res.get("references") or res.get("refs") or res.get("results") or []
            print(f"  elapsed : {dt:.2f}s")
            print(f"  refs    : {len(refs) if hasattr(refs,'__len__') else 'n/a'}")
            print(f"  answer  : {ans[:400]}")
            # remaining keys
            other = {k:v for k,v in res.items() if k not in ('answer','reply','text','references','refs','results')}
            if other:
                print(f"  other   : {list(other.keys())}")
        else:
            print(f"  elapsed : {dt:.2f}s")
            print(f"  result  : {str(res)[:400]}")
    except Exception as e:
        dt = time.time() - t0
        print(f"  FAIL in {dt:.2f}s: {type(e).__name__}: {str(e)[:300]}")
