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


class YouTubeService:
    BASE_URL = "https://www.googleapis.com/youtube/v3/videos"

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

    ###### youtube metadata 추출 ######
    def get_metadata(self, video_id: str) -> dict:
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

            return lines

        except Exception as e:
            return f"Error fetching transcript: {e}"

    def _run_stt_process(self, video_id: str):
        # STT 로직 구현부
        pass
