"""
[지식 입력 파이프라인]

실행 흐름 (모두 순차 실행):
  Step 1  collect_and_chunk          → 현지/수왕 담당  (자막 추출 + 정제 + 청킹)
  Step 2  run_intelligence_graph     → 채훈 담당      (LangGraph: 요약 → 벡터화 → 개요 생성)
  Step 3  update_status              → 자동           (Knowledge 상태 → COMPLETED)

Step 2 내부 LangGraph 흐름:
  [summarize_each_chunk] → [embed_summaries] → [generate_overview] → END
  (청크별 요약)            (요약문 벡터화)      (전체 개요 요약 — 노션 업로드용)

진입점: run_core_pipeline_task(video_id) — router_service.py에서 호출됨
"""
import asyncio
from typing import TypedDict
from pydantic import BaseModel, Field
from celery import shared_task, chain
from celery.utils.log import get_task_logger
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from app.core.config import settings

logger = get_task_logger(__name__)

# OpenAI 클라이언트
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


# --- Celery에서 async 함수를 실행하기 위한 헬퍼 ---
def run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        return loop.create_task(coro)
    else:
        return asyncio.run(coro)


# --- 더미 DB 작업 (실제 DB 로직으로 교체 예정) ---
async def dummy_async_db_operation(task_name: str, video_id: str, delay: int = 1):
    logger.info(f"[{task_name}] DB 작업 시뮬레이션 (video_id: {video_id})")
    await asyncio.sleep(delay)
    logger.info(f"[{task_name}] DB 작업 완료")
    return {"status": "success", "task_name": task_name}


# ==========================================
# LangGraph State 정의
# ==========================================
class IntelligenceState(TypedDict):
    """LangGraph 노드 간 공유되는 상태"""
    video_id: str
    chunks: list              # Step 1에서 넘어온 청크 리스트
    summarized_chunks: list   # 청크별 요약 결과
    embeddings: list          # 벡터화 결과
    title: str                # 영상 제목 (개요에서 생성)
    full_summary: str         # 전체 개요 요약 (노션 업로드용)
    category: str             # AI가 판별한 카테고리


# ==========================================
# LangGraph용 Structured Output 스키마
# ==========================================
class VideoOverview(BaseModel):
    """전체 개요 생성 시 OpenAI가 반환해야 하는 구조"""
    title: str = Field(description="영상의 핵심 주제를 나타내는 제목 (15자 이내)")
    full_summary: str = Field(description="영상 전체 내용을 3~5문장으로 요약")
    category: str = Field(description="영상의 카테고리 (예: 개발/IT, 경제, 자기계발, 교육 등)")


# ==========================================
# LangGraph 노드 1: 청크별 요약
# ==========================================
def summarize_each_chunk(state: IntelligenceState) -> dict:
    """각 청크의 content를 OpenAI로 요약"""
    video_id = state["video_id"]
    chunks = state["chunks"]

    logger.info(f"[LangGraph: 청크별 요약] 시작 (video_id: {video_id}, 청크 수: {len(chunks)})")

    summarized_chunks = []
    for chunk in chunks:
        try:
            response = openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "너는 유튜브 영상의 텍스트 조각을 요약하는 AI야. "
                            "핵심 인사이트와 정보 위주로 2~3문장으로 간결하게 요약해. "
                            "불필요한 인트로, 인사말, 광고 문구는 무시해."
                        ),
                    },
                    {"role": "user", "content": chunk["content"]},
                ],
            )
            summary = response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning(f"  청크 {chunk['chunk_order']} 요약 실패: {e}")
            summary = chunk["content"][:100] + "..."

        summarized_chunks.append({**chunk, "summary": summary})
        logger.info(f"  청크 {chunk['chunk_order']} 요약 완료")

    return {"summarized_chunks": summarized_chunks}


# ==========================================
# LangGraph 노드 2: 요약문 벡터화
# ==========================================
def embed_summaries_node(state: IntelligenceState) -> dict:
    """청크별 요약문을 OpenAI Embeddings로 벡터화"""
    video_id = state["video_id"]
    summarized_chunks = state["summarized_chunks"]
    texts = [chunk["summary"] for chunk in summarized_chunks]

    logger.info(f"[LangGraph: 벡터화] 시작 (video_id: {video_id}, 청크 수: {len(texts)})")

    embeddings = []
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        embeddings = [item.embedding for item in response.data]
        logger.info(f"  벡터 {len(embeddings)}개 생성 (차원: {len(embeddings[0])})")
    except Exception as e:
        logger.error(f"  Embedding API 호출 실패: {e}")

    return {"embeddings": embeddings}


# ==========================================
# LangGraph 노드 3: 전체 개요 생성 (노션 업로드용)
# ==========================================
def generate_overview(state: IntelligenceState) -> dict:
    """청크별 요약을 종합하여 영상 전체 제목/개요/카테고리 생성"""
    video_id = state["video_id"]
    summarized_chunks = state["summarized_chunks"]

    all_summaries = "\n".join(
        [f"[{c['chunk_order']}] {c['summary']}" for c in summarized_chunks]
    )

    logger.info(f"[LangGraph: 개요 생성] 시작 (video_id: {video_id})")

    try:
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "아래는 유튜브 영상의 청크별 요약 목록이야. "
                        "이 내용을 종합하여 영상 전체 제목, 전체 요약, 카테고리를 생성해. "
                        "이 요약은 노션 페이지에 게시될 예정이니 깔끔하고 읽기 쉽게 작성해."
                    ),
                },
                {"role": "user", "content": all_summaries},
            ],
            response_format=VideoOverview,
        )
        overview = response.choices[0].message.parsed
        title = overview.title
        full_summary = overview.full_summary
        category = overview.category
    except Exception as e:
        logger.warning(f"  전체 개요 생성 실패: {e}")
        title = f"영상 {video_id}"
        full_summary = all_summaries[:200]
        category = "미분류"

    logger.info(f"[LangGraph: 개요 생성] 완료 — 제목: {title}, 카테고리: {category}")

    return {"title": title, "full_summary": full_summary, "category": category}


# ==========================================
# LangGraph 그래프 조립
# ==========================================
def build_intelligence_graph():
    """
    LangGraph 그래프 구성:
      summarize_each_chunk → embed_summaries → generate_overview → END
    """
    graph = StateGraph(IntelligenceState)

    # 노드 등록
    graph.add_node("summarize_each_chunk", summarize_each_chunk)
    graph.add_node("embed_summaries", embed_summaries_node)
    graph.add_node("generate_overview", generate_overview)

    # 엣지 연결 (순차)
    graph.add_edge(START, "summarize_each_chunk")
    graph.add_edge("summarize_each_chunk", "embed_summaries")
    graph.add_edge("embed_summaries", "generate_overview")
    graph.add_edge("generate_overview", END)

    return graph.compile()

# 그래프 싱글톤 (Celery 워커 시작 시 1회 빌드)
intelligence_graph = build_intelligence_graph()


# ==========================================
# Step 1: 수집 + 청킹  (담당: 현지, 수왕)
# ==========================================
@shared_task(bind=True, name="knowledge.collect_and_chunk")
def collect_and_chunk(self, video_id: str):
    """자막 추출 → 정제 → 청킹 → DB 저장"""
    logger.info(f"[Step 1: 수집+청킹] 시작 (video_id: {video_id})")

    # ── 수정 포인트 (현지) ──
    # youtube_service.get_transcript(video_id) 호출하여 원본 자막 획득

    # ── 수정 포인트 (수왕) ──
    # transcript_refine() → 특수문자, 공백, 인트로 제거
    # transcript_chunking() → 텍스트 분할 (타임스탬프 유지)

    # ── 수정 포인트 (유리) ──
    # Knowledge 레코드 생성 (status=PROCESSING)
    # YoutubeKnowledgeChunk 테이블에 각 청크 저장

    run_async(dummy_async_db_operation("collect_and_chunk_DB", video_id, 2))

    # ── 더미 데이터 (위 로직 완성 시 교체) ──
    dummy_chunks = [
        {"chunk_order": 0, "content": "첫 번째 청크 텍스트...", "start_time": 0},
        {"chunk_order": 1, "content": "두 번째 청크 텍스트...", "start_time": 30000},
        {"chunk_order": 2, "content": "세 번째 청크 텍스트...", "start_time": 60000},
    ]

    return {
        "video_id": video_id,
        "chunks": dummy_chunks,
    }


# ==========================================
# Step 2: AI 추론 그래프  (담당: 채훈) ✅ LangGraph
# ==========================================
@shared_task(bind=True, name="knowledge.run_intelligence")
def run_intelligence_graph_task(self, data: dict):
    """LangGraph를 실행하여 요약 → 벡터화 → 개요 생성을 순차 수행"""
    video_id = data.get("video_id")
    chunks = data.get("chunks", [])

    logger.info(f"[Step 2: LangGraph] 시작 (video_id: {video_id})")

    # LangGraph 실행
    result = intelligence_graph.invoke({
        "video_id": video_id,
        "chunks": chunks,
        "summarized_chunks": [],
        "embeddings": [],
        "title": "",
        "full_summary": "",
        "category": "",
    })

    # ── 수정 포인트 (유리) ──
    # Knowledge 테이블에 title, summary, category 업데이트
    # YoutubeKnowledgeChunk에 벡터 저장
    run_async(dummy_async_db_operation("intelligence_DB_update", video_id, 1))

    logger.info(f"[Step 2: LangGraph] 완료 — 제목: {result['title']}")

    return {
        "video_id": video_id,
        "title": result["title"],
        "full_summary": result["full_summary"],       # 노션 업로드용
        "category": result["category"],
        "vector_count": len(result["embeddings"]),
        "summarized_chunks": result["summarized_chunks"],  # 청크별 요약
    }


# ==========================================
# Step 3: 완료 처리
# ==========================================
@shared_task(bind=True, name="knowledge.update_status")
def update_pipeline_status(self, data: dict):
    """Knowledge.status → COMPLETED 업데이트"""
    video_id = data.get("video_id")
    vector_count = data.get("vector_count", 0)
    title = data.get("title", "")

    logger.info(
        f"[Step 3: 완료] 파이프라인 종료 (video_id: {video_id}, "
        f"제목: {title}, 벡터 {vector_count}개)"
    )

    # ── 수정 포인트 (유리) ──
    # Knowledge.status = ProcessStatus.COMPLETED 로 DB 업데이트
    # TODO: 노션 업로드 트리거 (full_summary를 노션 페이지에 게시)
    run_async(dummy_async_db_operation("status_update_COMPLETED", video_id, 1))

    logger.info("지식 데이터 처리 완료! (Status -> COMPLETED)")
    return "Pipeline All Done"


# ==========================================
# 에러 핸들러
# ==========================================
@shared_task(bind=True, name="knowledge.handle_failure")
def handle_pipeline_failure(self, task_id, video_id: str):
    """에러 발생 시 Knowledge.status → FAILED"""
    logger.error(
        f"[Error] 파이프라인 에러 발생 (video_id: {video_id}, task: {task_id})"
    )
    run_async(dummy_async_db_operation("status_update_FAILED", video_id, 1))


# ==========================================
# 파이프라인 진입점 — router_service.py에서 호출
# ==========================================
def run_core_pipeline_task(video_id: str):
    """
    실행 순서 (순차 chain):
      Step 1 → Step 2 → Step 3
      (수집+청킹) → (LangGraph: 요약→벡터화→개요) → (완료)
    """
    logger.info(f"====== 파이프라인 트리거 (video_id: {video_id}) ======")

    workflow = chain(
        collect_and_chunk.s(video_id),        # Step 1: 현지/수왕
        run_intelligence_graph_task.s(),       # Step 2: 채훈 (LangGraph)
        update_pipeline_status.s(),           # Step 3: 완료
    ).on_error(handle_pipeline_failure.s(video_id))

    workflow.delay()

    return "Pipeline Started in Celery Background"
