import re
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth_dependencies import get_current_user
from app.models.user import User
from app.schemas.transcript_chunk import (
    ChunkStrategy,
    TranscriptChunkRequest,
    TranscriptChunkResponse,
)
from app.services.notion_connection_service import get_notion_connection
from app.services.transcript_chunking import (
    chunk_by_chars,
    chunk_by_semantic,
    chunk_by_time,
)
from app.services.transcript_refine import refine_transcript_segments
from app.services.youtube_service import YouTubeService
from app.tasks.knowledge_tasks import run_core_pipeline_task
from database import get_db

router = APIRouter()

youtube_service = YouTubeService()
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{11}$")


class YoutubeSummarizeRequest(BaseModel):
    url: str = Field(..., min_length=1)


class YoutubeSummarizeResponse(BaseModel):
    status: str
    video_id: str
    task_id: str | None = None


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
    body: TranscriptChunkRequest = Body(..., examples=[_CHUNK_REQUEST_EXAMPLE]),
) -> list[dict]:
    raw = youtube_service.get_transcript(body.video_id)
    if isinstance(raw, str):
        raise HTTPException(status_code=400, detail=raw)

    segments = refine_transcript_segments(raw)
    if not segments:
        return []

    if body.strategy == ChunkStrategy.time:
        return chunk_by_time(segments, body.time_window_ms)
    if body.strategy == ChunkStrategy.char:
        return chunk_by_chars(segments, body.max_chars, body.overlap_chars)
    return chunk_by_semantic(
        segments,
        body.semantic_threshold,
        body.semantic_min_paragraph_chars,
        body.semantic_min_chunk_chars,
    )


@router.get("/metadata")
def get_metadata_from_url(url: str):
    video_id = youtube_service.extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400, detail="Invalid Youtube URL")

    return youtube_service.get_metadata(video_id)


@router.post("/summarize", response_model=YoutubeSummarizeResponse)
def summarize_youtube_to_notion(
    body: YoutubeSummarizeRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> YoutubeSummarizeResponse:
    video_id = youtube_service.extract_youtube_video_id(body.url)
    if not video_id or not YOUTUBE_VIDEO_ID_PATTERN.fullmatch(video_id):
        raise HTTPException(status_code=400, detail="Invalid Youtube URL")

    connection = get_notion_connection(db, current_user.id)
    if connection is None or not connection.parent_page_id:
        raise HTTPException(
            status_code=409,
            detail="Notion is not ready. Connect Notion and select a parent page first.",
        )

    try:
        task_id = run_core_pipeline_task(video_id, current_user.id)
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Failed to queue summary task: {exc}",
        ) from exc

    return YoutubeSummarizeResponse(
        status="queued",
        video_id=video_id,
        task_id=task_id,
    )


@router.get("/stt_test")
def stt_test(url: str):
    video_id = youtube_service.extract_youtube_video_id(url)
    if not video_id:
        raise HTTPException(status_code=400)
    return youtube_service._run_stt_process(video_id)
