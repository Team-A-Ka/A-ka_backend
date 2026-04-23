import asyncio
import time
from celery import shared_task, chain, chord
from celery.utils.log import get_task_logger

logger = get_task_logger(__name__)

# --- Async Wrapper Helper ---
def run_async(coro):
    """
    Celery의 동기(Sync) 실행 환경에서 비동기(Async) 코루틴을 안전하게 실행하기 위한 헬퍼 함수입니다.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 만약 이미 이벤트루프가 존재한다면 (일반적으로 Celery 워커에서는 기본적으로 발생하지 않음)
        return loop.create_task(coro)
    else:
        # 독립적인 이벤트 루프 실행
        return asyncio.run(coro)

# 더미 비동기 DB 작업 시뮬레이션
async def dummy_async_db_operation(task_name: str, video_id: str, delay: int = 1):
    from database import async_session_maker
    
    async with async_session_maker() as session:
        # 실제 환경: session.execute(select(...))
        logger.info(f"[{task_name}] 비동기 DB 세션 오픈 (video_id: {video_id})")
        await asyncio.sleep(delay)
        logger.info(f"[{task_name}] 비동기 DB 작업 완료")
    
    return {"status": "success", "task_name": task_name}


# --- Phase 1: Sequential Task ---
@shared_task(bind=True, name="knowledge.phase1_sequential")
def phase1_sequential(self, video_id: str):
    logger.info(f"[Phase 1] 텍스트 청킹 및 1차 요약 시작 (video_id명: {video_id})")
    
    # 1. 텍스트 청크 DB 저장 
    run_async(dummy_async_db_operation("Phase1_DB_Save", video_id, 2))
    
    # 2. 다음 병렬 태스크(Phase 2)에 전달할 데이터 리턴
    return {
        "video_id": video_id,
        "phase1_result": "청킹 및 1차 요약 완료"
    }


# --- Phase 2: Parallel Task A (메인 파이프라인) ---
@shared_task(bind=True, name="knowledge.task_a_main")
def task_a_main_pipeline(self, data: dict):
    video_id = data.get("video_id")
    logger.info(f"[Task A] 2차 전체 영상 요약 및 카테고리 판별 시작 (video_id: {video_id})")
    
    # AI 등 I/O 작업 소요 시간 모사
    time.sleep(3) 

    # DB 업데이트 시뮬레이션
    run_async(dummy_async_db_operation("TaskA_DB_Update", video_id, 1))

    return {"task_a": "완료", "category": "개발/IT"}


# --- Phase 2: Parallel Task B (임베딩 파이프라인) ---
@shared_task(bind=True, name="knowledge.task_b_embedding")
def task_b_embedding_pipeline(self, data: dict):
    video_id = data.get("video_id")
    logger.info(f"[Task B] 텍스트 벡터화 및 Vector DB 적재 시작 (video_id: {video_id})")
    
    # 임베딩 API 호출 및 DB 적재 소요 시간 모사 (Task A와 동시에 돈다고 가정)
    time.sleep(4)
    
    # DB 벡터 삽입 시뮬레이션
    run_async(dummy_async_db_operation("TaskB_VectorDB_Insert", video_id, 1))

    return {"task_b": "완료", "vector_count": 150}


# --- Phase 3: Callback & Error Handling ---
@shared_task(bind=True, name="knowledge.update_status")
def update_pipeline_status(self, results: list, video_id: str):
    """
    Task A와 Task B가 모두 성공적으로 완료되었을 때 실행되는 Chord 콜백입니다.
    """
    logger.info(f"[Callback] 병렬 태스크 완료! 결과 취합 중... (video_id: {video_id})")
    logger.info(f"결과: {results}")
    
    # 비동기 DB를 통해 상태를 COMPLETED로 변경하는 로직
    run_async(dummy_async_db_operation(f"Status_Update_COMPLETED", video_id, 1))
    
    logger.info(f"지식 데이터 처리 완료! (Status -> COMPLETED)")
    return "Pipeline All Done"


@shared_task(bind=True, name="knowledge.handle_failure")
def handle_pipeline_failure(self, request, exc, traceback, video_id: str):
    """
    체인이나 병렬 파이프라인 중 예외나 타임아웃 발생 시 무한 대기를 방지하기 위한 콜백입니다.
    """
    logger.error(f"[Error] 파이프라인 에러 발생 (video_id: {video_id}). Exception: {exc}")
    
    # 에러 발생 시 상태를 FAILED로 변경
    run_async(dummy_async_db_operation(f"Status_Update_FAILED", video_id, 1))
    

# --- 파이프라인 단일 진입점 (Orchestrator) ---
def run_core_pipeline_task(video_id: str):
    """
    위 정의된 작업들을 Celery Canvas(chain, chord)를 사용하여 조립하고 실행합니다.
    순서: Phase 1 -> (Task A || Task B) -> Status Update
    """
    logger.info(f"====== 파이프라인 트리거 (video_id: {video_id}) ======")

    # Workflow 조립
    # 1. phase1 실행
    # 2. phase1 결과(`data`)가 task_a와 task_b의 인자로 각각 자동 분배됨
    # 3. 완료 시 update_status 호출
    workflow = chain(
        phase1_sequential.s(video_id),
        chord(
            [task_a_main_pipeline.s(), task_b_embedding_pipeline.s()], 
            update_pipeline_status.s(video_id)
        )
    ).on_error(handle_pipeline_failure.s(video_id))
    
    # 비동기 파이프라인 실행
    workflow.delay()
    
    return "Pipeline Started in Celery Background"
