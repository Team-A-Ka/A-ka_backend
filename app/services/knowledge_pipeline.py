import asyncio
from app.schemas.graph_state import IntelligenceState, VideoOverview
from celery import shared_task, chain
from celery.utils.log import get_task_logger
from openai import OpenAI
from langgraph.graph import StateGraph, START, END
from app.core.config import settings
from app.services.transcript_chunking import chunk_by_time
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService
from app.repositories.knowledge import (
    save_chunks_to_db,
    create_base,
    save_link_only,
    update_knowledge_after_langgraph,
)

# NOTE:
#   - Knowledge / YoutubeMetadata / YoutubeKnowledgeChunk 모델 직접 사용은
#     repositories 함수가 추가되는 #2~#4 작업에서 필요해질 예정.
#   - sqlalchemy.select / update 와 async_session_maker 도 마찬가지.
#   - 단독 작업 단계에서는 미사용이라 일단 주석 처리. 추가 작업 진입 시 해제.
# from app.models.knowledge import Knowledge, YoutubeMetadata, YoutubeKnowledgeChunk
# from sqlalchemy import select, update
# from database import async_session_maker

logger = get_task_logger(__name__)

# OpenAI 클라이언트 — 모듈 로드 시 1회 생성 (싱글톤)
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)


# IntelligenceState, VideoOverview는 app/schemas/graph_state.py에서 import


# ==========================================
# LangGraph 노드 1: 청크별 요약
# ==========================================
def summarize_each_chunk(state: IntelligenceState) -> dict:
    """각 청크의 content를 OpenAI로 요약"""
    video_id = state.get("video_id", "Unknown")
    chunks = state.get("chunks", [])

    logger.info(
        f"[LangGraph: 청크별 요약] 시작 (video_id: {video_id}, 청크 수: {len(chunks)})"
    )

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
                            "핵심 인사이트와 정보 위주로 2~4문장으로 간결하게 요약해. "
                            "불필요한 인트로, 인사말, 광고 문구는 무시해."
                        ),
                    },
                    {"role": "user", "content": chunk["content"]},
                ],
            )
            summary = response.choices[0].message.content.strip()
            if response.usage:
                logger.info(f"  [토큰 사용량] 청크 요약: {response.usage.total_tokens}") # llm이 사용중인 토큰 사용량 추적
        except Exception as e:
            logger.warning(f"  청크 {chunk.get('chunk_order', '?')} 요약 실패: {e}")
            summary = chunk.get("content", "")[:100] + "..." # 100개 청크면 100번 동기로 호출하는 식이라 나중에 비동기로 바꿔야함.

        summarized_chunks.append({**chunk, "summary": summary})
        # logger.info(f"  청크 요약 내용 {summarized_chunks}")
        logger.info(f"  청크 {chunk.get('chunk_order', '?')} 요약 완료")

    return {"summarized_chunks": summarized_chunks}


# ==========================================
# LangGraph 노드 2: 요약문 벡터화
# ==========================================
def embed_summaries_node(state: IntelligenceState) -> dict:
    """청크별 요약문을 OpenAI Embeddings로 벡터화"""
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])
    texts = [chunk.get("summary", "") for chunk in summarized_chunks]

    logger.info(
        f"[LangGraph: 벡터화] 시작 (video_id: {video_id}, 청크 수: {len(texts)})"
    )

    embeddings = []
    try:
        response = openai_client.embeddings.create(
            model="text-embedding-3-small",
            input=texts, 
        )
        embeddings = [item.embedding for item in response.data]
        if hasattr(response, "usage") and response.usage:
            logger.info(f"  [토큰 사용량] 임베딩: {response.usage.total_tokens}")
        logger.info(f"  벡터 {len(embeddings)}개 생성 (차원: {len(embeddings[0])})")
    except Exception as e:
        logger.error(f"  Embedding API 호출 실패: {e}")

    return {"embeddings": embeddings}
# 임베딩 파트 한번 호출로 모든 요약문을 벡터로 변환 가능. openai가 배치를 네이티브 지원해서 가능하다고 함. (뭔지 찾아봐야 함)

# ==========================================
# LangGraph 노드 3: 전체 개요 생성 (노션 업로드용)
# ==========================================
def generate_overview(state: IntelligenceState) -> dict:
    """청크별 요약을 종합하여 영상 전체 제목/개요/카테고리 생성"""
    video_id = state.get("video_id", "Unknown")
    summarized_chunks = state.get("summarized_chunks", [])

    all_summaries = "\n".join(
        [
            f"[{c.get('chunk_order', '?')}] {c.get('summary', '')}"
            for c in summarized_chunks
        ]
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
            response_format=VideoOverview, # graph_state VideoOVerview 불러와 사용, response_format 으로 넘겨 스키마에 맞춰 답을 만듬
        )
        overview = response.choices[0].message.parsed
        if response.usage:
            logger.info(f"  [토큰 사용량] 개요 생성: {response.usage.total_tokens}")
        title = overview.title
        full_summary = overview.full_summary
        category = overview.category
    except Exception as e:
        logger.warning(f"  전체 개요 생성 실패: {e}")
        title = f"영상 {video_id}"
        full_summary = all_summaries[:200]
        category = "미분류"

    logger.info(f"[LangGraph: 개요 생성] 완료 — 제목: {title}, 카테고리: {category}")

    return {"title": title, "full_summary": full_summary, "category": category} # dict로 리턴하는 거라 노드 하나로 키 3개 리턴


# ==========================================
# LangGraph 그래프 조립
# ==========================================
def build_intelligence_graph():
    """
    LangGraph 그래프 구성:
      summarize_each_chunk → embed_summaries → generate_overview → END
    """
    graph = StateGraph(IntelligenceState) # state 타입 지정

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


# 그래프 싱글톤 (Celery 워커 시작 시 1회 빌드) 매번 빌드 하지 않음, 워커 프로세스 부팅 시 한 번
intelligence_graph = build_intelligence_graph()


# ==========================================
# Step 1: 수집 + 청킹  (담당: 현지, 수왕)
# ==========================================
@shared_task(bind=True, name="knowledge.collect_and_chunk")
def collect_and_chunk(self, video_id: str):
    """자막 추출 → 정제 → 청킹 → DB 저장"""
    logger.info(f"[Step 1: 수집+청킹] 시작 (video_id: {video_id})")

    try:
        youtube_service = YouTubeService()

        try:
            ####### 메타데이터 추출 #######
            metadata = youtube_service.get_metadata(video_id)
            logger.info(f"영상 제목: {metadata['video_title']}")
            """ metadata 반환 형식
            {
            "video_id": video_id,
            "video_title": snippet["title"],
            "channel_name": snippet["channelTitle"],
            "duration": duration_ms,
            }
            """
        except Exception as e:
            logger.warning(f"메타데이터를 가져오지 못했습니다 {e}")
            metadata = {"video_id": video_id, "video_title": "Unknown"}

        ####### 자막 추출 #######
        logger.info(f"사용중인 API KEY 존재 여부: {bool(youtube_service.api_key)}")
        transcript_data = youtube_service.get_transcript(video_id)

        if isinstance(transcript_data, str) and transcript_data.startswith("Error"):
            logger.error(f"자막 추출 단계 최종 에러: {transcript_data}")
            raise ValueError(f"자막 추출 실패: {transcript_data}")
        logger.info(
            f"추출된 로우 데이터 개수: {len(transcript_data) if transcript_data else 0}"
        )

        ####### 정제 #######
        refine_seg = refine_transcript_segments(transcript_data)
        if not refine_seg:
            logger.warning("정제된 자막 데이터가 없습니다.")
            return {"video_id": video_id, "chunks": []}

        ####### 청킹 (청크 기법은 여기서 지정해야함) #######
        chunks = []
        chunks = chunk_by_time(refine_seg, 60000)
        logger.info(f"[Step 1] 완료: {len(chunks)} 개의 청크 생성")

        final_chunks = []
        for i, raw_chunk in enumerate(chunks):
            final_chunks.append(
                {
                    "chunk_order": i,
                    "content": raw_chunk.get("content", ""),
                    "start_time": raw_chunk.get("start_time", 0),
                }
            )

        # ── DB 저장 로직
        asyncio.run(save_chunks_to_db(video_id, metadata, final_chunks))

        logger.info(f"첫번째 청크 시작시간: {final_chunks[0]['start_time']}")
        logger.info(f"첫번째 청크 내용: {final_chunks[0]['content'][:50]}")

        return {
            "video_id": video_id,
            "metadata": metadata,
            "chunks": final_chunks,
        }
    except Exception as exc:
        logger.error(f"[Step 1] 오류 발생: {exc}")
        raise self.retry(exc=exc, countdown=5)


# ==========================================
# Step 2: AI 추론 그래프  (담당: 채훈) ✅ LangGraph
# ==========================================
@shared_task(bind=True, name="knowledge.run_intelligence")
def run_intelligence_graph_task(self, data: dict):
    """LangGraph를 실행하여 요약 → 벡터화 → 개요 생성을 순차 수행"""
    video_id = data.get("video_id")
    chunks = data.get("chunks", [])

    logger.info(f"[Step 2: LangGraph] 시작 (video_id: {video_id})")

    # ──────────────────────────────────────────
    # 빈 chunks 가드 (자막 추출/청킹 실패 방어)
    # ──────────────────────────────────────────
    # 자막 없는 영상이거나 Step 1이 빈 결과를 흘리면 chunks=[]가 들어옴.
    # 이대로 LangGraph에 넣으면:
    #   - summarize_each_chunk: for문 0회 → summarized_chunks=[] (조용히 통과)
    #   - embed_summaries_node: input=[] 로 OpenAI Embeddings API 호출 → BadRequestError
    #   - generate_overview: 빈 컨텍스트로 LLM 호출 → 헛소리 또는 fallback 진입
    # 결과: 그래프는 통과하지만 DB에 의미 없는 garbage가 저장됨.
    # 따라서 진입 전에 가드를 두고 fallback dict를 직접 리턴해 Step 3으로 넘김.
    # (status를 FAILED로 마킹하는 진짜 처리는 #4 handle_pipeline_failure 작업에서 보강 예정)
    if not chunks:
        logger.warning(
            f"[Step 2] chunks 비어있음 — LangGraph 스킵 (video_id: {video_id})"
        )
        return {
            "video_id": video_id,
            "title": f"영상 {video_id}",
            "full_summary": "자막을 추출할 수 없어 요약을 생성하지 못했습니다.",
            "category": "미분류",
            "vector_count": 0,
            "summarized_chunks": [],
        }

    # LangGraph 실행
    result = intelligence_graph.invoke(
        {
            "video_id": video_id,
            "chunks": chunks,
            "summarized_chunks": [],
            "embeddings": [],
            "title": "",
            "full_summary": "",
            "category": "",
        }
    )

    # ──────────────────────────────────────────
    # DB 반영 (#2)
    # ──────────────────────────────────────────
    # LangGraph가 만든 결과를 Knowledge + YoutubeKnowledgeChunk 에 UPDATE.
    #   - title, summary       → Knowledge
    #   - chunk별 summary      → YoutubeKnowledgeChunk.summary_detail
    #   - category 이름        → #6 작업(category lookup) 후 보강 예정
    #   - embeddings           → #7 작업(embedding 컬럼 추가) 후 별도 함수에서 처리 예정
    try:
        asyncio.run(
            update_knowledge_after_langgraph(
                video_id=video_id,
                title=result["title"],
                summary=result["full_summary"],
                summarized_chunks=result["summarized_chunks"],
            )
        )
    except Exception as e:
        # DB UPDATE 실패해도 chain 자체는 진행시키고 Step 3 / 핸들러에서 종합 처리.
        # (재시도 정책은 향후 정교화 — 일단 로그만)
        logger.error(f"[Step 2] update_knowledge_after_langgraph 실패: {e}")

    logger.info(f"[Step 2: LangGraph] 완료 — 제목: {result['title']}")

    return {
        "video_id": video_id,
        "title": result["title"],
        "full_summary": result["full_summary"],  # 노션 업로드용
        "category": result["category"],          # #6 작업에서 category_id 매핑에 사용
        "vector_count": len(result["embeddings"]),
        "summarized_chunks": result["summarized_chunks"],
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

    logger.info("지식 데이터 처리 완료! (Status -> COMPLETED)")
    return "Pipeline All Done"


# ==========================================
# 에러 핸들러
# ==========================================
@shared_task(bind=True, name="knowledge.handle_failure")
def handle_pipeline_failure(self, task_id, video_id: str):
    """에러 발생 시 Knowledge.status → FAILED

    chain의 .on_error()로 연결되어 Step 1/2/3 어느 곳에서 raise되든 호출됨.
    현재는 로깅만. 실제 DB UPDATE(status=FAILED)는 #4 작업에서 repository
    함수(mark_failed)를 추가한 뒤 여기서 호출 예정.
    """
    logger.error(
        f"[Error] 파이프라인 에러 발생 (video_id: {video_id}, task: {task_id})"
    )
    # TODO(#4): repositories.knowledge.mark_failed(video_id) 호출 추가


# ==========================================
# 파이프라인 진입점 — router_service.py에서 호출
# ==========================================
@shared_task(bind=True, name="knowledge.run_core_pipeline")
def run_core_pipeline_task(self, video_id: str):
    """
    실행 순서 (순차 chain):
      Step 1 → Step 2 → Step 3
      (수집+청킹) → (LangGraph: 요약→벡터화→개요) → (완료)
    """
    logger.info(f"====== 파이프라인 트리거 (video_id: {video_id}) ======")
    
    try:
    # 1. 파이프라인 시작 전에 Knowledge + YoutubeMetadata 빈 레코드 생성
        knowledge_db_id = asyncio.run(create_base(video_id))
        logger.info(f"DB 초기 레코드 생성 성공: {knowledge_db_id}")

    except Exception as e:
        logger.error(f"파이프라인 시작 실패 (DB 초기화 에러): {e}")
        return "Failed to start pipeline: DB Error"



    workflow = chain(
        collect_and_chunk.s(video_id),  # Step 1: 현지/수왕
        run_intelligence_graph_task.s(),  # Step 2: 채훈 (LangGraph)
        update_pipeline_status.s(),  # Step 3: 완료
    ).on_error(handle_pipeline_failure.s(video_id))

    workflow.delay()


# ==========================================
# 단순 링크 저장 (SAVE_ONLY) 진입점
# ==========================================
@shared_task(bind=True, name="knowledge.save_link_only")
def save_link_only_task(self, video_id: str):
    """SAVE_ONLY 의도: LangGraph 요약을 타지 않고 단순 링크만 저장."""
    logger.info(
        f"====== 단순 링크 저장 파이프라인 트리거 (video_id: {video_id}) ======"
    )

    try:
        # 1) 메타데이터 추출
        #    - YouTubeService.get_metadata 의 반환 키는 video_title / channel_name / duration / video_id.
        yt_service = YouTubeService()
        metadata = yt_service.get_metadata(video_id)
        title = metadata.get("video_title", f"영상 {video_id}")

        # 2) DB 저장 (Knowledge + YoutubeMetadata, status=COMPLETED)
        #    - chunks/embeddings 없음(SAVE_ONLY는 LangGraph 패스).
        #    - user_id 매핑은 #5 작업에서 추가. 현재는 repository 기본값(user_id=1) 사용.
        knowledge_id = asyncio.run(save_link_only(video_id, metadata))

        logger.info(f"[단순 저장 완료] knowledge_id={knowledge_id}, 제목: {title}")
        return {
            "video_id": video_id,
            "knowledge_id": str(knowledge_id),
            "title": title,
            "status": "COMPLETED",
        }
    except Exception as exc:
        logger.error(f"[단순 저장 에러] {exc}")
        # TODO(#4): mark_failed(video_id) 호출 추가
        raise self.retry(exc=exc, countdown=5)== 단순 링크 저장 파이프라인 트리거 (video_id: {video_id}) ======"
    )

    try:
        # 1) 메타데이터 추출
        #    - YouTubeService.get_metadata 의 반환 키는 video_title / channel_name / duration / video_id.
        yt_service = YouTubeService()
        metadata = yt_service.get_metadata(video_id)
        title = metadata.get("video_title", f"영상 {video_id}")

        # 2) DB 저장 (Knowledge + YoutubeMetadata, status=COMPLETED)
        #    - chunks/embeddings 없음(SAVE_ONLY는 LangGraph 패스).
        #    - user_id 매핑은 #5 작업에서 추가. 현재는 repository 기본값(user_id=1) 사용.
        knowledge_id = asyncio.run(save_link_only(video_id, metadata))

        logger.info(f"[단순 저장 완료] knowledge_id={knowledge_id}, 제목: {title}")
        return {
            "video_id": video_id,
            "knowledge_id": str(knowledge_id),
            "title": title,
            "status": "COMPLETED",
        }
    except Exception as exc:
        logger.error(f"[단순 저장 에러] {exc}")
        # TODO(#4): mark_failed(video_id) 호출 추가
        raise self.retry(exc=exc, countdown=5)