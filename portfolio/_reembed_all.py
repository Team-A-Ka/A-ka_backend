"""기존 청크의 summary_detail을 Gemini로 전수 재임베딩.

전제:
- OpenAI(1536) → Gemini(gemini-embedding-001 @ 1536)로 provider 전환.
- DB 컬럼 vector(1536) 그대로 유지 (옵션 D).
- 기존 임베딩은 OpenAI 임베딩 공간이라 새 Gemini 질의와 비교 불가 → 전수 덮어쓰기.

실행:
    python portfolio/_reembed_all.py --dry-run   # 대상만 카운트
    python portfolio/_reembed_all.py             # 실제 실행
    python portfolio/_reembed_all.py --batch 32  # 배치 크기 조정
"""
import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.llm import embed_texts, _resolve_embedding_provider
from database import SessionLocal

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("reembed")


def fetch_targets(session) -> list[tuple]:
    """summary_detail이 있는 모든 청크 (id, summary_detail). chunk_order로 정렬."""
    rows = session.execute(
        text(
            """
            SELECT id::text, summary_detail
              FROM youtube_knowledge_chunk
             WHERE summary_detail IS NOT NULL
               AND length(summary_detail) > 0
             ORDER BY knowledge_id, chunk_order
            """
        )
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def update_embeddings(session, pairs: list[tuple[str, list[float]]]) -> None:
    """(chunk_id, vector) 쌍을 일괄 UPDATE. pgvector 캐스팅 필요."""
    for chunk_id, vec in pairs:
        vec_literal = "[" + ",".join(f"{v:.7f}" for v in vec) + "]"
        session.execute(
            text(
                "UPDATE youtube_knowledge_chunk "
                "SET embedding = CAST(:v AS vector), updated_at = NOW() "
                "WHERE id = :id"
            ),
            {"v": vec_literal, "id": chunk_id},
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="대상 카운트만 출력")
    ap.add_argument("--batch", type=int, default=32, help="Gemini 배치 크기 (기본 32)")
    args = ap.parse_args()

    provider = _resolve_embedding_provider()
    log.info(f"resolved embedding provider = {provider}")
    if provider not in {"gemini", "google"}:
        log.warning(f"primary provider is '{provider}', not gemini — proceeding anyway.")

    session = SessionLocal()
    try:
        targets = fetch_targets(session)
        log.info(f"target chunks: {len(targets)}")
        if args.dry_run or not targets:
            return

        total = len(targets)
        done = 0
        t_start = time.time()
        BATCH = max(1, args.batch)

        for i in range(0, total, BATCH):
            batch = targets[i : i + BATCH]
            ids = [b[0] for b in batch]
            texts_in = [b[1] for b in batch]
            t0 = time.time()
            try:
                vectors = embed_texts(texts_in)
            except Exception as e:
                log.error(
                    f"batch {i}–{i+len(batch)-1} failed: {type(e).__name__}: {e}"
                )
                # 짧게 쉬고 다음 배치 시도 (rate limit/일시 오류 가정)
                time.sleep(2.0)
                continue

            if len(vectors) != len(batch):
                log.error(
                    f"batch {i}: got {len(vectors)} vectors for {len(batch)} inputs — skipping"
                )
                continue
            if vectors and len(vectors[0]) != 1536:
                log.error(f"batch {i}: unexpected dim={len(vectors[0])} (expected 1536)")
                return

            update_embeddings(session, list(zip(ids, vectors)))
            session.commit()
            done += len(batch)
            dt = time.time() - t0
            elapsed = time.time() - t_start
            log.info(
                f"  batch {i//BATCH + 1}: {len(batch)} chunks  "
                f"({dt:.2f}s, total {done}/{total}, "
                f"avg {elapsed/done:.2f}s/chunk, ETA {(total-done)*elapsed/max(done,1):.0f}s)"
            )

        log.info(
            f"DONE: re-embedded {done}/{total} chunks in {time.time()-t_start:.1f}s"
        )

        # 검증
        new_dim = session.execute(
            text(
                "SELECT vector_dims(embedding) FROM youtube_knowledge_chunk "
                "WHERE embedding IS NOT NULL LIMIT 1"
            )
        ).scalar()
        log.info(f"sample embedding dim in DB = {new_dim}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
