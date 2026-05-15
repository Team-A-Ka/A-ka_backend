import logging

from youtube_transcript_api import YouTubeTranscriptApi
from urllib.parse import urlparse, parse_qs
import os
import requests
from isodate import parse_duration

import tempfile
from pathlib import Path
import whisper
from yt_dlp import YoutubeDL
from ..core.config import settings


logger = logging.getLogger(__name__)


class YouTubeService:
    BASE_URL = "https://www.googleapis.com/youtube/v3/videos"
    OEMBED_URL = "https://www.youtube.com/oembed"

    # whisper_model (tiny < base < small < medium < large)
    def __init__(self, whisper_model_name: str = "base"):
        self.api = YouTubeTranscriptApi()
        self.api_key = settings.YOUTUBE_API_KEY
        self.whisper_model_name = whisper_model_name
        self._whisper_model = None

    ###### url에서 video_id 추출 ######
    def extract_youtube_video_id(self, url: str) -> str | None:
        parsed = urlparse(url)

        if parsed.hostname in ("www.youtube.com", "youtube.com"):
            if parsed.path == "/watch":
                return parse_qs(parsed.query).get("v", [None])[0]
            if parsed.path.startswith("/shorts/"):
                return parsed.path.split("/shorts/")[1].split("/")[0]

        if parsed.hostname == "youtu.be":
            return parsed.path.lstrip("/").split("/")[0]

        return None
    
    def is_shorts_url(self, url: str) -> bool:
        """URL을 확인하여 쇼츠 여부를 반환합니다."""
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return "/shorts/" in parsed.path
    
    ###### youtube metadata 추출 ######
    def get_metadata(self, video_id: str) -> dict:
        try:
            return self._fetch_metadata_via_data_api(video_id)
        except Exception as exc:
            logger.warning(
                "YouTube Data API failed for video_id=%s (%s); "
                "falling back to oEmbed.",
                video_id,
                exc,
            )

        oembed_metadata = self._fetch_metadata_via_oembed(video_id)
        if oembed_metadata is not None:
            return oembed_metadata

        raise ValueError(f"YouTube metadata not found for video_id={video_id}")

    def _fetch_metadata_via_data_api(self, video_id: str) -> dict:
        if not self.api_key:
            raise RuntimeError("YOUTUBE_API_KEY is not configured")

        params = {
            "part": "snippet,contentDetails",
            "id": video_id,
            "key": self.api_key,
        }

        resp = requests.get(self.BASE_URL, params=params, timeout=10)
        resp.raise_for_status()

        data = resp.json()
        items = data.get("items", [])
        if not items:
            raise ValueError("YouTube metadata not found")

        item = items[0]
        snippet = item["snippet"]
        content_details = item["contentDetails"]

        duration_iso = content_details["duration"]
        duration_ms = int(parse_duration(duration_iso).total_seconds() * 1000)

        return {
            "video_id": video_id,
            "video_title": snippet["title"],
            "channel_name": snippet["channelTitle"],
            "duration": duration_ms,
        }

    def _fetch_metadata_via_oembed(self, video_id: str) -> dict | None:
        """Fallback that uses the public, key-less oEmbed endpoint.

        Only title and channel name are available from oEmbed; duration is set
        to 0 and should be filled in later if needed.
        """
        try:
            resp = requests.get(
                self.OEMBED_URL,
                params={
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "format": "json",
                },
                timeout=10,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as exc:
            logger.warning(
                "YouTube oEmbed fallback failed for video_id=%s: %s",
                video_id,
                exc,
            )
            return None

        return {
            "video_id": video_id,
            "video_title": payload.get("title") or "Unknown",
            "channel_name": payload.get("author_name") or "Unknown",
            "duration": 0,
        }

    def get_transcript(self, video_id: str, language="ko"):
        """
        유투브 video_id와 언어코드로 자막(스크립트) 텍스트 반환.
        """
        try:
            transcript_list = self.api.list(video_id)
            transcript = None

            # 우선 한국어 수동 자막을 찾는다.
            try:
                # 1. 자막 추출 시도
                transcript = transcript_list.find_transcript([language])
            except Exception:
                # 없으면 자동 생성 자막을 찾는다.
                try:
                    transcript = transcript_list.find_generated_transcript([language])
                except Exception:
                    # 그래도 없으면 첫 번째 사용 가능한 자막 사용
                    try:
                        transcript = next(iter(transcript_list))

                    except Exception:
                        # 2. 자막이 없는 경우
                        # 여기서 STT 변환 로직(오디오 추출 -> Whisper 등)을 호출
                        return self._run_stt_process(video_id)

            transcript_data = transcript.fetch()
            lines = []

            for entry in transcript_data:
                if hasattr(entry, "text"):
                    text = entry.text
                    start = getattr(entry, "start", 0)
                else:
                    text = entry.get("text", "")
                    start = entry.get("start", 0)

                if text:
                    lines.append(
                        {
                            "start_time": int(start * 1000),
                            "text": text.strip(),
                        }
                    )
            if lines:
                return lines

            return self._run_stt_process(video_id)

        except Exception as e:
            return f"Error fetching transcript: {e}"

    ###### STT 구현 관련 함수  ######
    @property
    def whisper_model(self):
        if self._whisper_model is None:
            self._whisper_model = whisper.load_model(self.whisper_model_name)
        return self._whisper_model

    def _run_stt_process(self, video_id: str, language: str = "ko"):
        """
        1. 유튜브 오디오 다운로드
        2. Whisper로 전사
        3. start_time / text 형식으로 반환
        """
        audio_path = None

        try:
            audio_path = self._download_youtube_audio(video_id)

            result = self.whisper_model.transcribe(
                audio=audio_path,
                language=language,  # 한국어면 "ko"
                task="transcribe",  # 번역이 아니라 원문 전사
                verbose=False,
            )

            lines = []
            for seg in result.get("segments", []):
                text = seg.get("text", "").strip()
                start = seg.get("start", 0.0)

                if text:
                    lines.append(
                        {
                            "start_time": int(float(start) * 1000),
                            "text": text,
                        }
                    )

            return lines

        except Exception as e:
            return f"Error running Whisper STT: {e}"

        finally:
            if audio_path and os.path.exists(audio_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass

    def _download_youtube_audio(self, video_id: str) -> str:
        """
        yt-dlp로 유튜브 오디오만 내려받아 wav 파일 경로 반환
        ffmpeg 설치 필요
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        temp_dir = tempfile.mkdtemp(prefix="yt_audio_")
        output_template = str(Path(temp_dir) / "%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": output_template,
            "quiet": True,
            "noplaylist": True,
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "wav",
                    "preferredquality": "192",
                }
            ],
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            video_id = info["id"]

        wav_path = Path(temp_dir) / f"{video_id}.wav"
        if not wav_path.exists():
            raise FileNotFoundError(f"Audio file not found: {wav_path}")

        return str(wav_path)

    #################################
