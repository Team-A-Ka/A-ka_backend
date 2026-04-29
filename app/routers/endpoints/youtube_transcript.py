from fastapi import APIRouter, Body, HTTPException

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
def get_transcript(url: str):
    video_id = youtube_service.extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid Youtube URL")
    return youtube_service.get_transcript(video_id)


_CHUNK_REQUEST_EXAMPLE = {
    "video_id": "MKV6DTVmxwE",
    "language": "ko",
    "time_window_ms": 30_000,
    "max_chars": 500,
    "overlap_chars": 0,
    "semantic_threshold": 0.35,
    "semantic_min_paragraph_chars": 150,
    "semantic_min_chunk_chars": 0,
    "strategy": "semantic",
}


@router.post("/transcript/chunk", response_model=list[TranscriptChunkResponse])
def chunk_transcript(
    body: TranscriptChunkRequest = Body(..., example=_CHUNK_REQUEST_EXAMPLE),
) -> list[dict]:
    """``get_transcript``와 동일하게 자막을 가져온 뒤 정제하고 ``strategy``에 맞게 청킹한다."""
    raw = youtube_service.get_transcript(body.video_id)
    if isinstance(raw, str):
        raise HTTPException(status_code=400, detail=raw)
    segs = refine_transcript_segments(raw)  # 정제
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


@router.get("/metadata")
def get_metadata_from_url(url: str):
    video_id = youtube_service.extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid Youtube URL")

    metadata = youtube_service.get_metadata(video_id)
    return metadata


@router.get("/stt_test")
def stt_test(url: str):
    video_id = youtube_service.extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400)
    return youtube_service._run_stt_process(video_id)
