"""Throttled re-embed with exponential backoff for low embedding rate limits.

기존 _reembed_all.py가 429에서 배치를 그냥 스킵하는 문제를 보완:
- 작은 배치 + 배치 간 간격 + 배치별 지수 백오프 재시도.
- 단일 호출은 되는데 batchEmbedContents가 429나면 batch=1로 자동 축소.
"""
import sys, time, argparse
sys.path.insert(0, ".")
from sqlalchemy import text
from database import SessionLocal
from app.core.llm import embed_texts

ap = argparse.ArgumentParser()
ap.add_argument("--batch", type=int, default=4)
ap.add_argument("--gap", type=float, default=3.0, help="배치 간 기본 간격(s)")
ap.add_argument("--max-retries", type=int, default=6)
args = ap.parse_args()

s = SessionLocal()
rows = s.execute(text(
    "SELECT id::text, summary_detail FROM youtube_knowledge_chunk "
    "WHERE summary_detail IS NOT NULL AND length(summary_detail) > 0 "
    "AND embedding IS NULL ORDER BY knowledge_id, chunk_order"
)).fetchall()
targets = [(r[0], r[1]) for r in rows]
print(f"targets (no embedding yet): {len(targets)}")

def embed_with_backoff(texts_in):
    delay = 8.0
    for attempt in range(1, args.max_retries + 1):
        try:
            return embed_texts(texts_in)
        except Exception as e:
            msg = str(e)
            is429 = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            print(f"    attempt {attempt} FAIL ({type(e).__name__}, 429={is429}); "
                  f"backoff {delay:.0f}s")
            if attempt == args.max_retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 120)
    return None

done = 0
BATCH = max(1, args.batch)
t0 = time.time()
i = 0
while i < len(targets):
    batch = targets[i:i+BATCH]
    ids = [b[0] for b in batch]
    txts = [b[1] for b in batch]
    try:
        vecs = embed_with_backoff(txts)
    except Exception as e:
        print(f"  giving up on batch at {i}: {str(e)[:120]}")
        # batch=1로 축소 재시도
        if BATCH > 1:
            print("  -> reducing batch size to 1 and retrying this batch")
            BATCH = 1
            continue
        else:
            i += 1
            continue
    if vecs and len(vecs) == len(batch):
        for cid, v in zip(ids, vecs):
            lit = "[" + ",".join(f"{x:.7f}" for x in v) + "]"
            s.execute(text("UPDATE youtube_knowledge_chunk SET embedding=CAST(:v AS vector), "
                           "updated_at=NOW() WHERE id=:id"), {"v": lit, "id": cid})
        s.commit()
        done += len(batch)
        print(f"  ok batch {i//max(BATCH,1)} -> {done}/{len(targets)} (dim={len(vecs[0])})")
    i += BATCH
    time.sleep(args.gap)

emb = s.execute(text("SELECT COUNT(embedding) FROM youtube_knowledge_chunk")).scalar()
tot = s.execute(text("SELECT COUNT(*) FROM youtube_knowledge_chunk")).scalar()
print(f"DONE: embedded {done} this run in {time.time()-t0:.0f}s | DB now {emb}/{tot} with embedding")
s.close()
