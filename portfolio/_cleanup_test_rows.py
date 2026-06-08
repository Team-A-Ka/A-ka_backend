"""검증 중 생긴 테스트 잡 데이터 정리. 실제 코퍼스(user 21의 3편)는 보존."""
import sys
sys.path.insert(0, ".")
from sqlalchemy import text
from database import engine

REAL = ("o58i-LcqxVE", "F9dSJm2VPGk", "-A9RxJn5V2o")

with engine.begin() as c:
    # 실제 코퍼스(user 21 + 3편)가 아닌 knowledge 행의 id 수집
    ids = [r[0] for r in c.execute(text(
        """
        SELECT k.id FROM knowledge k
        LEFT JOIN youtube_metadata m ON m.knowledge_id = k.id
        WHERE NOT (k.user_id = 21 AND m.video_id = ANY(:real))
        """
    ), {"real": list(REAL)}).fetchall()]
    print("삭제 대상 knowledge:", len(ids))
    if ids:
        c.execute(text("DELETE FROM youtube_knowledge_chunk WHERE knowledge_id = ANY(:ids)"), {"ids": ids})
        c.execute(text("DELETE FROM youtube_metadata WHERE knowledge_id = ANY(:ids)"), {"ids": ids})
        c.execute(text("DELETE FROM knowledge WHERE id = ANY(:ids)"), {"ids": ids})

with engine.connect() as c:
    print("=== 남은 코퍼스 ===")
    for r in c.execute(text(
        "SELECT m.video_id, k.user_id, COUNT(ch.id) chunks, COUNT(ch.embedding) emb "
        "FROM knowledge k JOIN youtube_metadata m ON m.knowledge_id=k.id "
        "LEFT JOIN youtube_knowledge_chunk ch ON ch.knowledge_id=k.id "
        "GROUP BY m.video_id, k.user_id ORDER BY chunks"
    )):
        print("  ", tuple(r))
