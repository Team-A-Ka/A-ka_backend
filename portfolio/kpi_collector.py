"""KPI 자동 수집기 — UPLOAD 1편 + SEARCH N건을 한 번에 측정해 마크다운에 append.

사용법:
    python portfolio/kpi_collector.py upload --url https://youtu.be/XXX --label "5분 영상"
    python portfolio/kpi_collector.py search --query "물티슈 보존제 위험?" --label "Q1"
    python portfolio/kpi_collector.py search-batch --queries-file portfolio/queries.txt --label "RAG 5질문"
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text

from app.core.config import settings
from app.services.search_service import search_and_answer
from app.tasks.knowledge_tasks import run_core_pipeline_task
from database import SessionLocal


HERE = Path(__file__).resolve().parent
WORKER_LOG = HERE / "logs" / "celery_worker.log"
OUTPUT_MD = HERE / "KPI_측정결과.md"
USER_ID = 21
POLL_INTERVAL_S = 1
UPLOAD_TIMEOUT_S = 900  # 15분

# Gemini 2.5 flash-lite 단가 ($/1M tokens)
PRICE_INPUT_PER_1M = 0.10
PRICE_OUTPUT_PER_1M = 0.40
PRICE_EMBED_PER_1M = 0.15

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("kpi")


# ============================================================
# 공통 도구
# ============================================================
def parse_youtube_id(url: str) -> str:
    m = re.search(r"(?:v=|youtu\.be/|/embed/|/shorts/)([A-Za-z0-9_-]{11})", url)
    if not m:
        raise ValueError(f"cannot parse video_id from {url}")
    return m.group(1)


def read_log_tail(start_offset: int) -> list[str]:
    """워커 로그에서 start_offset 이후 모든 라인 반환."""
    if not WORKER_LOG.exists():
        return []
    with open(WORKER_LOG, "rb") as f:
        f.seek(start_offset)
        raw = f.read()
    return raw.decode("utf-8", errors="replace").splitlines()


def log_size() -> int:
    return WORKER_LOG.stat().st_size if WORKER_LOG.exists() else 0


_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")


def extract_step_timing(lines: list[str]) -> dict:
    """워커 로그 라인들에서 STEP1/2/3 경계 + LangGraph 노드 경계 시점 추출."""
    markers = {
        "step1_start": ("STEP1", "Using YouTube API key"),
        "step1_chunks_created": ("STEP1", "Created"),  # "Created N chunks"
        "step2_chunk_summary_start": ("STEP2", "LangGraph: chunk summary] start"),
        "step2_embedding_start": ("STEP2", "LangGraph: embedding] start"),
        "step2_embedding_done": ("STEP2", "embeddings created"),
        "step2_overview_start": ("STEP2", "LangGraph: overview] start"),
        "step2_overview_done": ("STEP2", "LangGraph: overview] done"),
        "step3_start": ("STEP3", "Category"),
        "step3_done": ("STEP3", "Completed"),
    }
    out: dict[str, str | None] = {k: None for k in markers}
    for ln in lines:
        ts_match = _TS_RE.search(ln)
        if not ts_match:
            continue
        ts = ts_match.group(1)
        for key, (step_tag, needle) in markers.items():
            if out[key] is not None:
                continue
            if step_tag in ln and needle in ln:
                out[key] = ts
    return out


def count_log_events(lines: list[str]) -> dict:
    """LLM/임베딩 호출 수, 실패 수 카운트."""
    return {
        "chunk_summary_failed": sum(1 for ln in lines if "chunk" in ln and "summary failed" in ln),
        "overview_failed": sum(1 for ln in lines if "overview generation failed" in ln),
        "embedding_block_done": sum(1 for ln in lines if "embeddings created" in ln),
        "any_429": sum(1 for ln in lines if "RESOURCE_EXHAUSTED" in ln or "429" in ln),
    }


# ============================================================
# LangSmith 토큰 수집
# ============================================================
def langsmith_token_summary(since_dt: datetime) -> dict:
    """최근 N분 안의 모든 run을 가져와 토큰 총합 산출."""
    try:
        from langsmith import Client
    except Exception:
        return {"error": "langsmith not installed"}

    try:
        client = Client()
        # 모든 nested run 포함 — execution_order 필터 제거 (이전 버전에선 최상위만 잡혔음)
        runs = list(
            client.list_runs(
                project_name=settings.LANGCHAIN_PROJECT,
                start_time=since_dt,
            )
        )
        in_tok = 0
        out_tok = 0
        llm_calls = 0
        embed_calls = 0
        type_counts: dict[str, int] = {}
        for r in runs:
            rt = r.run_type or "unknown"
            type_counts[rt] = type_counts.get(rt, 0) + 1
            # LangSmith Run 객체는 prompt_tokens / completion_tokens / total_tokens 속성을 가짐
            # (구버전은 outputs.usage_metadata, 더 구버전은 extra.invocation_params.usage)
            pt = getattr(r, "prompt_tokens", None) or 0
            ct = getattr(r, "completion_tokens", None) or 0
            if rt == "llm":
                llm_calls += 1
                # fallback: dig into outputs
                if not (pt or ct) and r.outputs:
                    meta = r.outputs.get("usage_metadata") or {}
                    pt = pt or int(meta.get("input_tokens") or 0)
                    ct = ct or int(meta.get("output_tokens") or 0)
            elif "embed" in rt.lower():
                embed_calls += 1
            in_tok += int(pt or 0)
            out_tok += int(ct or 0)
        return {
            "llm_calls": llm_calls,
            "embedding_calls": embed_calls,
            "input_tokens": in_tok,
            "output_tokens": out_tok,
            "total_runs_seen": len(runs),
            "run_type_counts": type_counts,
        }
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ============================================================
# UPLOAD 측정
# ============================================================
def run_upload(url: str, label: str) -> dict:
    video_id = parse_youtube_id(url)
    log.info(f"[UPLOAD] label={label!r}  url={url}  video_id={video_id}")

    # 워커 로그 시작 오프셋 기록
    log_off = log_size()
    t0 = time.time()
    since_dt = datetime.now(timezone.utc)

    dispatch_result = run_core_pipeline_task(url, video_id, USER_ID, include_similar=False)
    log.info(f"[UPLOAD] dispatched in {time.time()-t0:.2f}s  -> {dispatch_result}")

    # DB 폴링: status COMPLETED/FAILED까지
    session = SessionLocal()
    transitions = []  # list of (elapsed, status, chunks, emb, summary_len)
    final_row = None
    prev_state = None
    try:
        start = time.time()
        while time.time() - start < UPLOAD_TIMEOUT_S:
            row = session.execute(
                text(
                    """
                    SELECT k.id::text, k.status, k.title, k.summary, k.category_id,
                           c.name AS cat_name,
                           COUNT(ch.id) FILTER (WHERE ch.id IS NOT NULL) AS chunk_count,
                           COUNT(ch.embedding) FILTER (WHERE ch.embedding IS NOT NULL) AS emb_count
                      FROM knowledge k
                      LEFT JOIN youtube_metadata m ON m.knowledge_id = k.id
                      LEFT JOIN category c ON c.id = k.category_id
                      LEFT JOIN youtube_knowledge_chunk ch ON ch.knowledge_id = k.id
                     WHERE m.video_id = :vid AND k.user_id = :uid
                     GROUP BY k.id, c.name
                    """
                ),
                {"vid": video_id, "uid": USER_ID},
            ).first()
            if row:
                status = row[1].value if hasattr(row[1], "value") else str(row[1])
                state = (status, int(row[6]), int(row[7]), len(row[3] or ""))
                if state != prev_state:
                    transitions.append((time.time() - start, *state))
                    prev_state = state
                if status in ("COMPLETED", "FAILED"):
                    final_row = row
                    break
            session.commit()
            time.sleep(POLL_INTERVAL_S)
    finally:
        session.close()

    total_wall = time.time() - t0

    # 워커 로그에서 단계별 시점 + 이벤트 카운트
    new_lines = read_log_tail(log_off)
    step_ts = extract_step_timing(new_lines)
    events = count_log_events(new_lines)

    # 단계별 추정 시간 (사용 가능한 마커끼리 빼서)
    def diff(a: str | None, b: str | None) -> float | None:
        if not a or not b:
            return None
        try:
            d1 = datetime.strptime(a, "%Y-%m-%d %H:%M:%S")
            d2 = datetime.strptime(b, "%Y-%m-%d %H:%M:%S")
            return (d2 - d1).total_seconds()
        except Exception:
            return None

    step_durations = {
        "step1_chunking": diff(step_ts["step1_start"], step_ts["step2_chunk_summary_start"]),
        "step2_chunk_summary": diff(step_ts["step2_chunk_summary_start"], step_ts["step2_embedding_start"]),
        "step2_embedding": diff(step_ts["step2_embedding_start"], step_ts["step2_embedding_done"]),
        "step2_overview": diff(step_ts["step2_overview_start"], step_ts["step2_overview_done"]),
        "step3_publish": diff(step_ts["step3_start"], step_ts["step3_done"]),
    }

    # LangSmith 토큰 (10초 정도 기다린 후 — 트레이스 propagate 시간)
    time.sleep(8)
    ls = langsmith_token_summary(since_dt)

    chunks = int(final_row[6]) if final_row else 0
    embeds = int(final_row[7]) if final_row else 0
    title = final_row[2] if final_row else None
    summary = final_row[3] if final_row else None
    cat_name = final_row[5] if final_row else None

    # 추정 LLM 호출 수 (chunk 요약 N + overview 1 + 카테고리 1)
    est_llm_calls = chunks + 2
    est_embed_calls = 1  # batch 1회

    # LangSmith에서 실측 토큰 받았으면 비용 계산
    if "input_tokens" in ls:
        cost_in = ls["input_tokens"] / 1_000_000 * PRICE_INPUT_PER_1M
        cost_out = ls["output_tokens"] / 1_000_000 * PRICE_OUTPUT_PER_1M
        cost_total = cost_in + cost_out
    else:
        cost_in = cost_out = cost_total = None

    result = {
        "label": label,
        "url": url,
        "video_id": video_id,
        "title": title,
        "category": cat_name,
        "model_chat": settings.GEMINI_MODEL,
        "model_embed": settings.GEMINI_EMBEDDING_MODEL,
        "embed_dim": settings.GEMINI_EMBEDDING_DIM,
        "total_wall_s": round(total_wall, 2),
        "chunks": chunks,
        "embeddings": embeds,
        "summary_len": len(summary or ""),
        "step_durations_s": step_durations,
        "estimated_llm_calls": est_llm_calls,
        "estimated_embedding_calls": est_embed_calls,
        "events": events,
        "langsmith": ls,
        "cost_input_usd": cost_in,
        "cost_output_usd": cost_out,
        "cost_total_usd": cost_total,
        "transitions": transitions,
        "measured_at": datetime.now().isoformat(timespec="seconds"),
    }
    return result


# ============================================================
# SEARCH 측정
# ============================================================
def run_search(query: str, label: str) -> dict:
    log.info(f"[SEARCH] label={label!r}  query={query!r}")
    since_dt = datetime.now(timezone.utc)
    t0 = time.time()
    try:
        res = search_and_answer(USER_ID, query)
        elapsed = time.time() - t0
        ans = ""
        sources = []
        chunks_used = 0
        if isinstance(res, dict):
            ans = res.get("answer") or res.get("reply") or ""
            sources = res.get("sources") or res.get("references") or []
            chunks_used = len(res.get("chunks") or [])
        ok = True
        err = None
    except Exception as e:
        elapsed = time.time() - t0
        ans = ""
        sources = []
        chunks_used = 0
        ok = False
        err = f"{type(e).__name__}: {e}"

    time.sleep(4)
    ls = langsmith_token_summary(since_dt)
    if "input_tokens" in ls:
        cost = ls["input_tokens"] / 1_000_000 * PRICE_INPUT_PER_1M + ls["output_tokens"] / 1_000_000 * PRICE_OUTPUT_PER_1M
    else:
        cost = None

    return {
        "label": label,
        "query": query,
        "elapsed_s": round(elapsed, 2),
        "ok": ok,
        "error": err,
        "answer_len": len(ans),
        "answer_preview": (ans[:200] + "…") if len(ans) > 200 else ans,
        "sources_count": len(sources) if hasattr(sources, "__len__") else 0,
        "chunks_used": chunks_used,
        "model_chat": settings.GEMINI_MODEL,
        "model_embed": settings.GEMINI_EMBEDDING_MODEL,
        "langsmith": ls,
        "cost_total_usd": cost,
        "measured_at": datetime.now().isoformat(timespec="seconds"),
    }


# ============================================================
# 마크다운 append
# ============================================================
def append_md(section_title: str, payload: dict | list) -> None:
    OUTPUT_MD.parent.mkdir(parents=True, exist_ok=True)
    is_new = not OUTPUT_MD.exists()
    with open(OUTPUT_MD, "a", encoding="utf-8") as f:
        if is_new:
            f.write("# A-KA KPI 측정 결과\n\n")
            f.write(f"> 모델: chat=`{settings.GEMINI_MODEL}` / embed=`{settings.GEMINI_EMBEDDING_MODEL}` ({settings.GEMINI_EMBEDDING_DIM}d)\n")
            f.write(f"> 측정 시작: {datetime.now().isoformat(timespec='seconds')}\n\n")
        f.write(f"\n## {section_title}\n\n")
        f.write("```json\n")
        f.write(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        f.write("\n```\n")


# ============================================================
# CLI
# ============================================================
def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_up = sub.add_parser("upload")
    p_up.add_argument("--url", required=True)
    p_up.add_argument("--label", required=True)

    p_s = sub.add_parser("search")
    p_s.add_argument("--query", required=True)
    p_s.add_argument("--label", required=True)

    p_sb = sub.add_parser("search-batch")
    p_sb.add_argument("--queries-file", required=True)
    p_sb.add_argument("--label", required=True)

    args = ap.parse_args()

    if args.cmd == "upload":
        res = run_upload(args.url, args.label)
        append_md(f"UPLOAD — {args.label}", res)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    elif args.cmd == "search":
        res = run_search(args.query, args.label)
        append_md(f"SEARCH — {args.label}", res)
        print(json.dumps(res, ensure_ascii=False, indent=2, default=str))

    elif args.cmd == "search-batch":
        queries = [
            line.strip() for line in Path(args.queries_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        results = []
        for i, q in enumerate(queries, 1):
            results.append(run_search(q, f"{args.label}-Q{i}"))
        # 평균
        oks = [r for r in results if r["ok"]]
        if oks:
            avg = sum(r["elapsed_s"] for r in oks) / len(oks)
            mn = min(r["elapsed_s"] for r in oks)
            mx = max(r["elapsed_s"] for r in oks)
        else:
            avg = mn = mx = None
        summary = {
            "label": args.label,
            "count": len(results),
            "ok_count": len(oks),
            "elapsed_avg_s": round(avg, 2) if avg is not None else None,
            "elapsed_min_s": round(mn, 2) if mn is not None else None,
            "elapsed_max_s": round(mx, 2) if mx is not None else None,
            "results": results,
        }
        append_md(f"SEARCH BATCH — {args.label}", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
