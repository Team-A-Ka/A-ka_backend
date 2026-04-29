from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from app.services.intelligence_service import intelligence_graph
from app.services.search_service import search_graph

router = APIRouter()


def get_mermaid_html(title: str, mermaid_code: str) -> str:
    """Mermaid 텍스트를 입력받아 브라우저에서 그려주는 HTML 템플릿 반환"""
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>{title} - LangGraph Visualization</title>
        <script type="module">
            import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
            mermaid.initialize({{ startOnLoad: true, theme: 'default' }});
        </script>
        <style>
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background-color: #f8f9fa;
                color: #333;
                display: flex;
                flex-direction: column;
                align-items: center;
                padding: 40px;
            }}
            h2 {{ color: #2c3e50; margin-bottom: 30px; }}
            .mermaid-container {{
                background: white;
                padding: 30px;
                border-radius: 12px;
                box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
                overflow: auto;
                max-width: 100%;
            }}
        </style>
    </head>
    <body>
        <h2>{title}</h2>
        <div class="mermaid-container">
            <div class="mermaid">
                {mermaid_code}
            </div>
        </div>
    </body>
    </html>
    """


@router.get("/{graph_name}", response_class=HTMLResponse)
def render_graph(graph_name: str):
    """
    브라우저에서 /api/v1/debug/graph/{graph_name} 형태로 접속 시 해당 랭그래프를 시각화하여 반환합니다.
    """
    if graph_name == "knowledge":
        # 지식/업로드 파이프라인 그래프
        code = intelligence_graph.get_graph().draw_mermaid()
        return get_mermaid_html("지식 업로드 파이프라인 (knowledge_pipeline.py)", code)

    elif graph_name == "search":
        # RAG 검색 파이프라인 그래프
        code = search_graph.get_graph().draw_mermaid()
        return get_mermaid_html("검색 파이프라인 (search_service.py)", code)

    else:
        # 나중에 새로운 LangGraph가 추가되면 elif로 추가해주시면 됩니다!
        raise HTTPException(
            status_code=404,
            detail=f"그래프를 찾을 수 없습니다: '{graph_name}'. 지원되는 그래프: 'knowledge', 'search'",
        )
