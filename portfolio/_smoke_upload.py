"""스모크 테스트: 단일 영상 UPLOAD 파이프라인 한 사이클.

- Celery worker가 살아있어야 함 (현재 셀러리 워커 celery@MAX666 확인됨).
- 진행 상황을 DB로 폴링 (knowledge.status, 청크 수, summary 채워짐 여부).
- 종료 후 단계별 시간을 표로 출력.
"""
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.tasks.knowledge_tasks import run_core_pipeline_task
from database import SessionLocal


URL = "https://www.youtube.com/watch?v=o58i-LcqxVE"
VIDEO_ID = "o58i-LcqxVE"
USER_ID = 21
POLL_INTERVAL_S = 2
TIMEOUT_S = 600  # 10분


def snapshot(session, video_id):
    """현재 video_id의 처리 상태 한 줄 요약."""
    row = session.execute(
        text(
            """
            SELECT k.id, k.status, k.summary, k.title, k.category_id,
                   COUNT(c.id) FILTER (WHERE c.id IS NOT NULL) AS chunk_count,
                   COUNT(c.embedding) FILTER (WHERE c.embedding IS NOT NULL) AS emb_count,
                   k.created_at, k.updated_at
              FROM knowledge k
              LEFT JOIN youtube_metadata m ON m.knowledge_id = k.id
              LEFT JOIN youtube_knowledge_chunk c ON c.knowledge_id = k.id
             WHERE m.video_id = :vid AND k.user_id = :uid
             GROUP BY k.id, k.status, k.summary, k.title, k.category_id, k.created_at, k.updated_at
            """
        ),
        {"vid": video_id, "uid": USER_ID},
    ).first()
    return row


def main():
    print(f"[smoke] dispatching pipeline: url={URL}  user_id={USER_ID}")
    t_dispatch = time.time()
    result = run_core_pipeline_task(URL, VIDEO_ID, USER_ID, include_similar=False)
    print(f"[smoke] dispatch returned in {time.time()-t_dispatch:.2f}s: {result}")

    session = SessionLocal()
    try:
        t_start = time.time()
        prev_status = None
        prev_chunks = -1
        prev_emb = -1
        prev_summary_len = -1
        history = []

        while time.time() - t_start < TIMEOUT_S:
            row = snapshot(session, VIDEO_ID)
            if not row:
                print(f"  [{time.time()-t_start:5.1f}s] no row yet…")
                time.sleep(POLL_INTERVAL_S)
                continue

            kid, status, summary, title, cat_id, chunks, emb, c_at, u_at = row
            status_str = status.value if hasattr(status, "value") else str(status)
            summary_len = len(summary or "")
            changed = (
                status_str != prev_status
                or chunks != prev_chunks
                or emb != prev_emb
                or summary_len != prev_summary_len
            )
            if changed:
                elapsed = time.time() - t_start
                msg = (
                    f"  [{elapsed:5.1f}s] status={status_str:9s} "
                    f"chunks={chunks:3d} emb={emb:3d} "
                    f"summary={summary_len:4d}ch cat={cat_id} "
                    f"title={(title or '')[:40]}"
                )
                print(msg)
                history.append((elapsed, status_str, chunks, emb, summary_len))
                prev_status, prev_chunks, prev_emb, prev_summary_len = (
                    status_str, chunks, emb, summary_len,
                )

            if status_str in ("COMPLETED", "FAILED"):
                break
            session.commit()  # release locks
            time.sleep(POLL_INTERVAL_S)

        print()
        print("=" * 60)
        print("FINAL")
        print("=" * 60)
        row = snapshot(session, VIDEO_ID)
        if row:
            kid, status, summary, title, cat_id, chunks, emb, c_at, u_at = row
            status_str = status.value if hasattr(status, "value") else str(status)
            total = (u_at - c_at).total_seconds() if c_at and u_at else None
            print(f"knowledge_id : {kid}")
            print(f"title        : {title}")
            print(f"status       : {status_str}")
            print(f"category_id  : {cat_id}")
            print(f"chunks       : {chunks}  (with_embedding={emb})")
            print(f"summary_len  : {len(summary or '')}")
            print(f"created_at   : {c_at}")
            print(f"updated_at   : {u_at}")
            print(f"total time   : {total:.1f}s" if total else "total time   : n/a")
            print()
            print("HISTORY:")
            for elapsed, st, ch, em, sl in history:
                print(f"  {elapsed:6.1f}s  status={st:9s}  chunks={ch:3d}  emb={em:3d}  summary={sl:4d}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
