"""``get_transcript``로 받은 원시 자막 줄을 청킹 전에 정제한다."""


def refine_transcript_segments(raw: list[dict]) -> list[dict]:
    """YouTube API 형태의 세그먼트를 청킹 입력용으로 정리한다.

    - ``start_time``을 정수(ms)로 통일
    - ``text`` 앞뒤 공백 제거 후 빈 줄 제거
    - ``start_time`` 오름차순 정렬
    """
    out: list[dict] = []
    for row in raw:
        text = (row.get("text") or "").strip()
        if not text:
            continue
        try:
            st = int(row["start_time"])
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"start_time": st, "text": text})
    out.sort(key=lambda r: r["start_time"])
    return out
