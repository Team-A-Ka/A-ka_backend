"""Build A-KA_포트폴리오_이채훈.pdf from 01 + 02 + 05 markdown via headless Edge.

Mermaid 지원:
- ```mermaid ... ``` 블록을 <pre class="mermaid">로 보존
- mermaid.js 10.x CDN을 head에 로드
- Edge headless의 --virtual-time-budget으로 렌더링 완료 대기
"""
import html as html_lib
import os
import pathlib
import re
import subprocess
import sys
import time

import markdown

HERE = pathlib.Path(__file__).parent
FILES = [
    HERE / "01_대표프로젝트_AKA.md",
    HERE / "02_프로필_역량_요약.md",
    HERE / "05_1페이지_요약본.md",
]
OUT_HTML = HERE / "_combined.html"
OUT_PDF = HERE / "A-KA_포트폴리오_이채훈.pdf"

# Mermaid CDN — v10.x (stable, no module-script requirement)
MERMAID_CDN = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"

CSS = """
@page { size: A4; margin: 18mm 16mm 18mm 16mm; }
* { box-sizing: border-box; }
body {
  font-family: "Malgun Gothic", "맑은 고딕", "Apple SD Gothic Neo", sans-serif;
  font-size: 10.5pt; line-height: 1.55; color: #222;
  max-width: 100%; margin: 0; padding: 0;
}
h1 { font-size: 18pt; margin: 18px 0 10px; border-bottom: 2px solid #333; padding-bottom: 4px; page-break-before: always; }
h1:first-of-type { page-break-before: avoid; }
h2 { font-size: 14pt; margin: 16px 0 8px; border-bottom: 1px solid #aaa; padding-bottom: 3px; }
h3 { font-size: 12pt; margin: 12px 0 6px; color: #1a4480; }
h4 { font-size: 11pt; margin: 10px 0 4px; }
p, li { margin: 4px 0; }
code { font-family: "Consolas", "D2Coding", monospace; background: #f4f4f4; padding: 1px 4px; border-radius: 3px; font-size: 9.5pt; }
pre { background: #f6f8fa; border: 1px solid #ddd; border-radius: 4px; padding: 8px 10px; overflow-x: auto; font-size: 9pt; line-height: 1.4; page-break-inside: avoid; }
pre code { background: transparent; padding: 0; }
/* Mermaid 컨테이너는 코드블록 스타일 제외하고 SVG가 자연스럽게 보이도록 */
pre.mermaid {
  background: transparent;
  border: none;
  padding: 6px 0;
  text-align: center;
  font-family: "Malgun Gothic", sans-serif;
  font-size: 11pt;
  page-break-inside: avoid;
}
pre.mermaid svg { max-width: 100%; height: auto; }
blockquote { border-left: 4px solid #1a4480; background: #f6f9fc; margin: 8px 0; padding: 6px 12px; color: #444; }
table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #ccc; padding: 5px 7px; text-align: left; vertical-align: top; }
th { background: #eef2f7; font-weight: 600; }
img { max-width: 100%; height: auto; display: block; margin: 8px auto; page-break-inside: avoid; }
hr { border: none; border-top: 1px solid #ccc; margin: 14px 0; }
a { color: #1a4480; text-decoration: none; }
strong { color: #111; }
"""


_MERMAID_BLOCK_RE = re.compile(
    r"<pre><code class=\"language-mermaid\">(.*?)</code></pre>",
    re.DOTALL,
)


def _replace_mermaid_blocks(html_body: str) -> tuple[str, int]:
    """fenced_code가 만든 <pre><code class="language-mermaid">...</code></pre>를
    <pre class="mermaid">...(unescaped)...</pre>로 변환. (변환된 HTML, 카운트) 반환."""
    count = 0

    def _sub(m: re.Match) -> str:
        nonlocal count
        count += 1
        # markdown lib는 fenced_code 내부를 HTML escape함 (& < > ).
        # mermaid가 원본 텍스트를 받도록 unescape.
        raw = html_lib.unescape(m.group(1))
        return f'<pre class="mermaid">{raw}</pre>'

    new_html = _MERMAID_BLOCK_RE.sub(_sub, html_body)
    return new_html, count


def main():
    parts = []
    for f in FILES:
        parts.append(f.read_bytes().decode("utf-8", errors="replace"))
    combined_md = "\n\n<div style='page-break-after: always'></div>\n\n".join(parts)

    html_body = markdown.markdown(
        combined_md,
        extensions=["fenced_code", "tables", "toc", "sane_lists"],
    )
    html_body, mermaid_count = _replace_mermaid_blocks(html_body)
    print(f"[mermaid] {mermaid_count} block(s) converted to <pre class='mermaid'>")

    full = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><title>A-KA 포트폴리오 — 이채훈</title>
<style>{CSS}</style>
<script src="{MERMAID_CDN}"></script>
</head><body>
{html_body}
<script>
  if (window.mermaid) {{
    window.mermaid.initialize({{ startOnLoad: true, theme: 'neutral', securityLevel: 'loose' }});
  }}
</script>
</body></html>"""
    OUT_HTML.write_text(full, encoding="utf-8")
    print(f"[1/2] HTML written: {OUT_HTML}  ({len(full):,} bytes)")

    edge = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
    if not os.path.exists(edge):
        print(f"[FAIL] Edge not found at {edge}")
        sys.exit(1)
    file_url = "file:///" + str(OUT_HTML).replace("\\", "/")
    # --virtual-time-budget: 페이지 로드 후 N ms 만큼 가상 시간을 진행시킨 뒤 PDF 출력.
    #   네트워크(CDN 로드)·setTimeout·rAF·Promise 체인 등이 모두 그 안에 흐름.
    #   wall-clock sleep보다 결정적(deterministic)이라 mermaid 같은 async 렌더에 적합.
    # --run-all-compositor-stages-before-draw: 모든 compositor 단계 완료 후 캡처.
    cmd = [
        edge,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--virtual-time-budget=10000",
        "--run-all-compositor-stages-before-draw",
        f"--print-to-pdf={OUT_PDF}",
        "--print-to-pdf-no-header",
        file_url,
    ]
    print("[2/2] Running Edge headless (virtual-time-budget=10s for mermaid render)...")
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    dt = time.time() - t0
    if r.returncode != 0 or not OUT_PDF.exists():
        print(f"  rc={r.returncode}  elapsed={dt:.1f}s")
        print("STDOUT:", r.stdout[-800:])
        print("STDERR:", r.stderr[-800:])
        sys.exit(1)
    size = OUT_PDF.stat().st_size
    print(f"[OK] PDF: {OUT_PDF}  ({size/1024:.1f} KB, {dt:.1f}s)")


if __name__ == "__main__":
    main()
