from fastapi import APIRouter, HTTPException, Query

from app.schemas.transcript_chunk import (
    ChunkStrategy,
    TranscriptChunkResponse,
    TranscriptChunkRequest,
)
from app.services.transcript_chunking import (
    chunk_by_chars,
    chunk_by_semantic,
    chunk_by_time,
)
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService

router = APIRouter()

youtube_service = YouTubeService()


@router.get("/transcript")
def get_transcript(video_id: str = Query(...), language: str = Query("ko")):
    return youtube_service.get_transcript(video_id, language)


@router.post("/transcript/chunk", response_model=list[TranscriptChunkResponse])
def chunk_transcript(body: TranscriptChunkRequest) -> list[dict]:
    """``get_transcript``와 동일하게 자막을 가져온 뒤 정제하고 ``strategy``에 맞게 청킹한다."""
    raw = youtube_service.get_transcript(body.video_id)
    if isinstance(raw, str):
        raise HTTPException(status_code=400, detail=raw)
    segs = refine_transcript_segments(raw) # 정제
    if not segs:
        return []
    # 시간 기반
    if body.strategy == ChunkStrategy.time:
        return chunk_by_time(segs, body.time_window_ms)
    # 글자수 기반
    if body.strategy == ChunkStrategy.char:
        return chunk_by_chars(segs, body.max_chars, body.overlap_chars)
    # 문맥 기반
    return chunk_by_semantic(
        segs,
        body.semantic_threshold,
        body.semantic_min_paragraph_chars,
        body.semantic_min_chunk_chars,
    )
