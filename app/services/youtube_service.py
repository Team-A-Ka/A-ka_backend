from youtube_transcript_api import YouTubeTranscriptApi


class YouTubeService:
    def __init__(self):
        self.api = YouTubeTranscriptApi()

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
