"""
**전략별 청킹**
- ``chunk_by_time``: 버킷에 쌓인 구간의 (암시적 끝 시각 중 최대 − 첫 ``start_time``)이 ``window_ms`` 이상이면 한 청크로 확정.
- ``chunk_by_chars``: 줄을 공백으로 이어 붙인 뒤 ``max_chars`` 단위로 자름.
  단어 경계(공백)를 선호하고, ``overlap_chars``만큼 다음 윈도우와 겹침.
- ``chunk_by_semantic``: 문장 단위 유닛을 만든 뒤, 이웃 유닛끼리 유사도로 같은 청크에 붙일지/끊을지 결정.
  짧은 청크는 ``min_chunk_chars``로 후처리 병합 가능.

**내부 흐름**
``_normalize_segments``로 빈 줄 제거·``start_time`` 정리 후, 각 줄의 재생 구간 끝은
``_segment_end_ms``로만 계산한다.

**청크 dict 출력 형태** (API와 동일): ``start_time``(ms), ``content``.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import TypedDict


class NormalizedSegment(TypedDict):
    """청킹 전처리 후 한 줄 자막: 시작(ms), 본문."""

    start_time: int
    text: str


class SemanticUnit(TypedDict):
    """시멘틱 청킹의 최소 유닛(문장 또는 짧은 문장의 병합). 시각은 겹치는 자막 큐 기준."""

    char_start: int
    char_end: int
    text: str
    t_start: int
    t_end: int


# # 하위 호환용: 예전 이름 ParagraphUnit == SemanticUnit
# ParagraphUnit = SemanticUnit


def _segment_end_ms(norm: list[NormalizedSegment], idx: int) -> int:
    """``norm[idx]`` 한 줄이 덮는 구간의 끝 시각(ms): 다음 줄 ``start_time``, 없으면 +2초."""
    st = norm[idx]["start_time"]
    if idx + 1 < len(norm):
        nxt = norm[idx + 1]["start_time"]
        return nxt if nxt > st else st + 500
    return st + 2_000


def _normalize_segments(segments: list[dict]) -> list[NormalizedSegment]:
    """빈 텍스트 제거, ``start_time``·``text``만 갖는 줄 리스트로 만든다."""
    out: list[NormalizedSegment] = []
    for seg in segments:
        start = int(seg["start_time"])
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        out.append({"start_time": start, "text": text})
    out.sort(key=lambda s: s["start_time"])
    return out


def _full_text_and_spans(
    norm: list[NormalizedSegment],
) -> tuple[str, list[tuple[int, int, int]]]:
    """이어 붙인 전체 문자열과 각 줄의 문자 구간 ``[start, end)`` + ``norm`` 인덱스."""
    spans: list[tuple[int, int, int]] = []
    offset = 0
    for i, seg in enumerate(norm):
        if i > 0:
            offset += 1
        s = offset
        offset += len(seg["text"])
        spans.append((s, offset, i))
    full = " ".join(s["text"] for s in norm)
    return full, spans


def _char_index_to_time(
    char_index: int,
    spans: list[tuple[int, int, int]],
    norm: list[NormalizedSegment],
    full_len: int,
) -> int:
    """이어 붙인 전체 문자열에서 ``char_index``에 대응하는 대략의 시각(ms)."""
    if not spans or full_len <= 0:
        return 0
    pos = max(0, min(char_index, full_len - 1))
    for i, (s, e, idx) in enumerate(spans):
        st = norm[idx]["start_time"]
        en = _segment_end_ms(norm, idx)
        if s <= pos < e:
            local = pos - s
            denom = max(e - s, 1)
            frac = local / denom
            return int(st + frac * (en - st))
        if i + 1 < len(spans):
            ns = spans[i + 1][0]
            if e <= pos < ns:
                return int(en)
    return int(_segment_end_ms(norm, spans[-1][2]))


def _merge_chunk(bucket: list[NormalizedSegment]) -> dict:
    """시간 청킹 등에서 모은 ``NormalizedSegment`` 묶음을 API 형태 청크 dict로 합친다."""
    text = " ".join(s["text"] for s in bucket)
    return {
        "start_time": bucket[0]["start_time"],
        "content": text.strip(),
    }


def chunk_by_time(
    segments: list[dict],
    window_ms: int,
) -> list[dict]:
    """누적 재생 구간이 ``window_ms`` 이상이 될 때마다 자막 줄을 한 청크로 묶는다."""
    norm = _normalize_segments(segments)
    if not norm:
        return []

    chunks: list[dict] = []
    bucket_idx: list[int] = []
    span_start: int | None = None

    for i, seg in enumerate(norm):
        if not bucket_idx:
            span_start = seg["start_time"]
        bucket_idx.append(i)
        span_end = max(_segment_end_ms(norm, j) for j in bucket_idx)
        assert span_start is not None
        if span_end - span_start >= window_ms:
            chunks.append(_merge_chunk([norm[j] for j in bucket_idx]))
            bucket_idx = []
            span_start = None

    if bucket_idx:
        chunks.append(_merge_chunk([norm[j] for j in bucket_idx]))
    return chunks


def chunk_by_chars(
    segments: list[dict],
    max_chars: int,
    overlap_chars: int,
) -> list[dict]:
    """이어 붙인 전체 텍스트를 ``max_chars`` 단위로 자르되, 가능하면 공백에서 끊고 겹침을 둔다.

    각 조각의 ``start_time``은 잘린 문자 구간의 시작·끝을 자막 시간에 사상해 한 시각으로 둔다.
    """
    norm = _normalize_segments(segments)
    if not norm:
        return []

    full, spans = _full_text_and_spans(norm)
    if not full:
        return []

    full_len = len(full)
    overlap_chars = min(overlap_chars, max(0, max_chars - 1))
    chunks: list[dict] = []
    i = 0
    n = full_len
    while i < n:
        end = min(n, i + max_chars)
        if end < n:
            cut = full.rfind(" ", i + max_chars // 2, end)
            if cut == -1 or cut <= i:
                cut = end
            end = cut
        piece = full[i:end].strip()
        if piece:
            t0 = _char_index_to_time(i, spans, norm, full_len)
            t1 = _char_index_to_time(max(end - 1, i), spans, norm, full_len)
            chunks.append(
                {
                    "start_time": min(t0, t1),
                    "content": piece,
                }
            )
        if end >= n:
            break
        i = max(end - overlap_chars, i + 1)

    return chunks


def _tokenize(text: str) -> list[str]:
    """시멘틱 유사도용: 공백이 아닌 연속 문자열을 소문자 토큰 리스트로 분리한다."""
    return re.findall(r"\S+", text.lower())


def _cosine_counter(a: Counter, b: Counter) -> float:
    """단어 빈도 ``Counter`` 두 개 사이의 코사인 유사도(0~1 근처)."""
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _time_bounds_for_char_range(
    char_start: int,
    char_end: int,
    seg_spans: list[tuple[int, int, int]],
    norm: list[NormalizedSegment],
) -> tuple[int, int]:
    """``[char_start, char_end)``와 겹치는 자막 줄들의 최소 시작·최대 끝 시각(ms, 끝은 암시적 구간)."""
    t_starts: list[int] = []
    t_ends: list[int] = []
    for cs, ce, idx in seg_spans:
        if ce <= char_start or cs >= char_end:
            continue
        t_starts.append(norm[idx]["start_time"])
        t_ends.append(_segment_end_ms(norm, idx))
    if not t_starts:
        return 0, 0
    return min(t_starts), max(t_ends)


# split_sentences_ko 전용: 경계 뒤의 공백까지 한 번에 잡아 split
# 문장 끝: ASCII 마침표류 + 한국어 종결(공백까지 소비)
_SENT_SPLIT_KO = re.compile(
    r"(?<=[.!?。])\s+"
    r"|(?<=습니다\.)\s+|(?<=입니다\.)\s+|(?<=니다\.)\s+|(?<=었습니다\.)\s+|(?<=겠습니다\.)\s+"
    r"|(?<=드립니다\.)\s+|(?<=습니다\?)\s+|(?<=습니까\?)\s+|(?<=을까요\?)\s+|(?<=까요\?)\s+"
    r"|(?<=어요\.)\s+|(?<=예요\.)\s+|(?<=에요\.)\s+|(?<=이에요\.)\s+|(?<=이에요\?)\s+"
    r"|(?<=죠\.)\s+|(?<=죠\?)\s+|(?<=지요\.)\s+|(?<=지요\?)\s+"
    r"|(?<=다\.)\s+|(?<=요\.)\s+"
    r"|(?<=[가-힣]까\?)\s+"
)


def split_sentences_ko(text: str) -> list[str]:
    """
    공백 정규화 후 문장 단위로 분리. 자막에 흔한 종결(습니다/니다/다/요 등)과 . ? ! 를 경계로 삼는다.

    경계 패턴은 모듈 상단 ``_SENT_SPLIT_KO``에 정의됨. 매칭이 없으면 통째로 한 문장으로 취급.
    """
    work = re.sub(r"\s+", " ", text).strip()
    if not work:
        return []
    parts = [p.strip() for p in _SENT_SPLIT_KO.split(work) if p.strip()]
    if not parts:
        return [work]
    return parts


def _norm_ws_segments(norm: list[NormalizedSegment]) -> list[NormalizedSegment]:
    """각 자막 줄 텍스트 안의 연속 공백을 하나로 줄여 문장 분리·인덱스와 맞춘다."""
    out: list[NormalizedSegment] = []
    for s in norm:
        t = re.sub(r"\s+", " ", s["text"]).strip()
        if not t:
            continue
        out.append(
            {
                "start_time": s["start_time"],
                "text": t,
            }
        )
    return out


def _sentence_strings_to_units(
    full: str,
    seg_spans: list[tuple[int, int, int]],
    norm: list[NormalizedSegment],
    sentences: list[str],
) -> list[SemanticUnit]:
    """분리된 문장 문자열 각각을 ``full`` 내 문자 구간과 대응하는 ``t_start``/``t_end``로 올린다."""
    units: list[SemanticUnit] = []
    cursor = 0
    for sent in sentences:
        st = sent.strip()
        if not st:
            continue
        pos = full.find(st, cursor)
        if pos == -1:
            pos = cursor
        cs, ce = pos, pos + len(st)
        ts, te = _time_bounds_for_char_range(cs, ce, seg_spans, norm)
        units.append(
            {
                "char_start": cs,
                "char_end": ce,
                "text": st,
                "t_start": ts,
                "t_end": te,
            }
        )
        cursor = ce
        while cursor < len(full) and full[cursor] == " ":
            cursor += 1
    return units


def _merge_short_sentence_units(
    units: list[SemanticUnit],
    merge_under: int,
) -> list[SemanticUnit]:
    """문장 유닛 텍스트 길이가 ``merge_under`` 미만이면 다음 유닛과 하나로 합친다."""
    if merge_under <= 0 or len(units) <= 1:
        return units
    out: list[SemanticUnit] = []
    buf: SemanticUnit | None = None
    for u in units:
        if buf is None:
            buf = {**u}
            continue
        if len(buf["text"]) < merge_under:
            buf["text"] = f"{buf['text']} {u['text']}".strip()
            buf["char_end"] = u["char_end"]
            buf["t_end"] = u["t_end"]
        else:
            out.append(buf)
            buf = {**u}
    if buf is not None:
        out.append(buf)
    return out


def _build_semantic_sentence_units(
    norm: list[NormalizedSegment],
    min_merge_chars: int,
) -> list[SemanticUnit]:
    """정규화 세그먼트에서 한국어 문장 경계로 유닛을 만들고, 짧은 유닛을 ``min_merge_chars`` 기준으로 병합한다."""
    norm_ws = _norm_ws_segments(norm)
    if not norm_ws:
        return []
    full, seg_spans = _full_text_and_spans(norm_ws)
    if not full:
        return []
    sents = split_sentences_ko(full)
    units = _sentence_strings_to_units(full, seg_spans, norm_ws, sents)
    return _merge_short_sentence_units(units, merge_under=min_merge_chars)


def _join_sentence_chunk_texts(texts: list[str]) -> str:
    """시멘틱 청크에 묶인 여러 문장 유닛 텍스트를 공백으로 이어 한 문자열로 만든다."""
    return " ".join(t.strip() for t in texts if t.strip())


def _chunk_time_bounds(units: list[SemanticUnit], indices: list[int]) -> tuple[int, int]:
    """문장 유닛 인덱스 ``indices``에 해당하는 구간의 최소 ``t_start``·최대 ``t_end``(ms)."""
    t0 = min(units[j]["t_start"] for j in indices)
    t1 = max(units[j]["t_end"] for j in indices)
    return t0, t1


def chunk_by_semantic(
    segments: list[dict],
    similarity_threshold: float,
    min_paragraph_chars: int = 200,
    min_chunk_chars: int = 0,
) -> list[dict]:
    """
    자막 큐를 공백 정규화·한국어 문장 경계로 나눈 **문장 유닛**을 만든 뒤,
    유닛과 유닛 사이의 단어 백 코사인 유사도로 청크를 묶거나 끊는다.
    청크 경계는 항상 문장 유닛 경계이므로, 유사도만으로 문장 중간을 자르지 않는다.

    min_paragraph_chars: 짧은 문장 조각(이 글자 수 미만)은 다음 문장과 한 유닛으로 합친 뒤 시멘틱에 넘긴다.
    min_chunk_chars: 유사도로 만든 최종 청크가 이 글자 수 미만이면 다음 청크와 합침(0이면 비활성).
    """
    norm = _normalize_segments(segments)
    if not norm:
        return []

    merge_under = max(15, min_paragraph_chars)
    units = _build_semantic_sentence_units(norm, min_merge_chars=merge_under)
    if not units:
        return []
    if len(units) == 1:
        return _merge_output_chunks_by_min_chars([_merge_chunk(norm)], min_chunk_chars)

    chunks: list[dict] = []
    current_indices: list[int] = [0]

    for idx in range(1, len(units)):
        cur_text = _join_sentence_chunk_texts([units[j]["text"] for j in current_indices])
        nxt = units[idx]["text"]
        ca = Counter(_tokenize(cur_text))
        cb = Counter(_tokenize(nxt))
        sim = _cosine_counter(ca, cb)
        if sim < similarity_threshold and cur_text.strip():
            t_start, _t_end = _chunk_time_bounds(units, current_indices)
            chunks.append(
                {
                    "start_time": t_start,
                    "content": cur_text,
                }
            )
            current_indices = [idx]
        else:
            current_indices.append(idx)

    if current_indices:
        t_start, _t_end = _chunk_time_bounds(units, current_indices)
        chunks.append(
            {
                "start_time": t_start,
                "content": _join_sentence_chunk_texts(
                    [units[j]["text"] for j in current_indices]
                ),
            }
        )

    return _merge_output_chunks_by_min_chars(chunks, min_chunk_chars)


def _merge_output_chunks_by_min_chars(
    chunks: list[dict],
    min_chunk_chars: int,
) -> list[dict]:
    """시멘틱 청킹 직후 청크들 중 ``content`` 길이가 ``min_chunk_chars`` 미만이면 순서대로 다음 청크와 합친다.

    ``min_chunk_chars``가 0 이하이거나 청크가 0~1개면 입력을 그대로 반환한다.
    """
    if min_chunk_chars <= 0 or len(chunks) <= 1:
        return chunks
    out: list[dict] = []
    i = 0
    n = len(chunks)
    while i < n:
        cur = dict(chunks[i])
        i += 1
        while len(cur["content"]) < min_chunk_chars and i < n:
            nxt = chunks[i]
            cur["content"] = f"{cur['content']} {nxt['content']}".strip()
            i += 1
        out.append(cur)
    return out
