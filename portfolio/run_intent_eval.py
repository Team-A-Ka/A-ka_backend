"""의도 분류 평가셋 50 케이스 자동 실행기.

- portfolio/intent_eval_set.md의 표를 파싱
- ChatCommandService.analyze_intent()를 직접 호출 (Celery 거치지 않음)
- 결과를 portfolio/intent_eval_result.md로 저장 (오답 분석 포함)
"""
from __future__ import annotations

import json
import logging
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.services.chat_command import ChatCommandService

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("eval")

EVAL_MD = Path(__file__).resolve().parent / "intent_eval_set.md"
OUTPUT_MD = Path(__file__).resolve().parent / "intent_eval_result.md"


def parse_cases(md_text: str) -> list[dict]:
    """intent_eval_set.md에서 케이스 50개 추출.

    표 라인 패턴:
      | 1 | `이거 요약해줘 https://youtu.be/dQw4w9WgXcQ` | UPLOAD | 기본형 |
    """
    cases = []
    # 표 행 패턴 (셀 4개)
    row_re = re.compile(
        r"^\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*([A-Z_]+)\s*\|\s*(.+?)\s*\|\s*$",
        re.MULTILINE,
    )
    for m in row_re.finditer(md_text):
        case_id = int(m.group(1))
        raw_input = m.group(2)
        gold = m.group(3).strip()
        note = m.group(4).strip()

        # input 셀에서 백틱 코드(`…`) 추출. 백틱이 없으면 통째로 사용.
        input_text = raw_input
        # **bold** 마커 제거
        input_text = re.sub(r"\*\*", "", input_text)
        # 양 끝 백틱·작은따옴표·큰따옴표 정리 (여러 케이스에서 다양)
        # 첫 백틱 안의 내용 우선
        bt = re.search(r"`([^`]+)`", raw_input)
        if bt:
            input_text = bt.group(1)
        else:
            input_text = re.sub(r"^['\"`]|['\"`]$", "", input_text).strip()

        cases.append({
            "id": case_id,
            "input": input_text,
            "gold": gold,
            "note": note,
        })
    return cases


def run_eval(cases: list[dict]) -> list[dict]:
    svc = ChatCommandService()
    results = []
    for c in cases:
        t0 = time.time()
        try:
            intent, detected_url, embedded_question = svc.analyze_intent(c["input"])
            elapsed = time.time() - t0
            pred = intent.value if hasattr(intent, "value") else str(intent)
            ok = pred == c["gold"]
            results.append({
                **c,
                "predicted": pred,
                "detected_url": detected_url,
                "embedded_question": embedded_question,
                "elapsed_s": round(elapsed, 2),
                "correct": ok,
                "error": None,
            })
            mark = "OK" if ok else "WRONG"
            print(f"  [#{c['id']:>2d}] [{mark:5}] gold={c['gold']:13s} pred={pred:13s} ({elapsed:.2f}s)  {c['input'][:60]}")
        except Exception as e:
            elapsed = time.time() - t0
            results.append({
                **c,
                "predicted": None,
                "detected_url": None,
                "embedded_question": None,
                "elapsed_s": round(elapsed, 2),
                "correct": False,
                "error": f"{type(e).__name__}: {e}",
            })
            print(f"  [#{c['id']:>2d}] [ERR  ] gold={c['gold']:13s}  {type(e).__name__}: {str(e)[:80]}")
    return results


def write_report(results: list[dict]) -> None:
    total = len(results)
    correct = sum(1 for r in results if r["correct"])
    errors = sum(1 for r in results if r["error"])

    # per-intent accuracy
    by_intent: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_intent[r["gold"]].append(r)

    # confusion matrix
    confusion: dict[tuple[str, str], int] = Counter()
    for r in results:
        confusion[(r["gold"], r["predicted"] or "ERROR")] += 1

    avg_elapsed = sum(r["elapsed_s"] for r in results) / max(1, total)

    lines = []
    lines.append("# 의도 분류 평가셋 — 실행 결과")
    lines.append("")
    lines.append(f"> 측정일: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"> 모델: `{settings.GEMINI_MODEL}` (chat) / provider=`{settings.LLM_PRIMARY_PROVIDER}`")
    lines.append(f"> 케이스 수: **{total}** / 정답: **{correct}** / 오류: {errors}")
    lines.append(f"> **정답률: {correct}/{total} = {correct/total*100:.1f}%**")
    lines.append(f"> 평균 분류 시간: {avg_elapsed:.2f}s")
    lines.append("")

    lines.append("## 인텐트별 정확도")
    lines.append("")
    lines.append("| 인텐트 | 정답 / 전체 | 정확도 |")
    lines.append("|---|---|---|")
    for gold in ["UPLOAD", "SAVE_ONLY", "FIND_SIMILAR", "SEARCH", "UNKNOWN"]:
        rs = by_intent.get(gold, [])
        n = len(rs)
        c = sum(1 for r in rs if r["correct"])
        pct = (c / n * 100) if n else 0
        lines.append(f"| {gold} | {c}/{n} | {pct:.0f}% |")
    lines.append("")

    lines.append("## 혼동 행렬 (gold → predicted)")
    lines.append("")
    intents = ["UPLOAD", "SAVE_ONLY", "FIND_SIMILAR", "SEARCH", "UNKNOWN", "ERROR"]
    header = "| gold \\ pred | " + " | ".join(intents) + " |"
    sep = "|" + "---|" * (len(intents) + 1)
    lines.append(header)
    lines.append(sep)
    for gold in intents[:-1]:  # ERROR는 gold에 없음
        row = [gold]
        for pred in intents:
            n = confusion.get((gold, pred), 0)
            row.append(str(n) if n else "·")
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    lines.append("## 오답 케이스 상세")
    lines.append("")
    wrong = [r for r in results if not r["correct"]]
    if not wrong:
        lines.append("(오답 없음 — 50/50)")
    else:
        lines.append("| # | 입력 | gold | 예측 | 비고 | 원인 추정 |")
        lines.append("|---|---|---|---|---|---|")
        for r in wrong:
            cause = ""
            if r["error"]:
                cause = f"호출 자체 실패: {r['error'][:60]}"
            elif r["gold"] == "UNKNOWN" and r["predicted"] in ("UPLOAD", "SAVE_ONLY", "FIND_SIMILAR"):
                cause = "프롬프트 인젝션·인용문·URL 단편을 의도로 잘못 해석"
            elif r["gold"] != "UNKNOWN" and r["predicted"] == "UNKNOWN":
                cause = "정상 의도를 못 잡고 UNKNOWN으로 fallback"
            else:
                cause = "분류 경계 모호"
            inp = r["input"].replace("|", "\\|")
            lines.append(f"| {r['id']} | `{inp[:60]}` | {r['gold']} | {r['predicted'] or 'ERROR'} | {r['note']} | {cause} |")
    lines.append("")

    lines.append("## 전체 케이스 결과 (JSON)")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    lines.append("```")

    OUTPUT_MD.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n결과 저장: {OUTPUT_MD}")
    print(f"정답률: {correct}/{total} = {correct/total*100:.1f}%")


def main():
    md = EVAL_MD.read_text(encoding="utf-8", errors="replace")
    cases = parse_cases(md)
    # gold가 5-way 인텐트인 것만 (intent 정의 표 같은 게 섞일 수 있어서 필터)
    valid = {"UPLOAD", "SAVE_ONLY", "FIND_SIMILAR", "SEARCH", "UNKNOWN"}
    cases = [c for c in cases if c["gold"] in valid]
    if len(cases) != 50:
        print(f"⚠️ 파싱된 케이스 수가 50이 아님: {len(cases)}")
    print(f"실행: {len(cases)} 케이스")
    print()
    results = run_eval(cases)
    write_report(results)


if __name__ == "__main__":
    main()
