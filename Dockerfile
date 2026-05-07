# 1단계: Build stage (컴파일 및 패키지 설치)
FROM python:3.12-slim AS builder

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# 컴파일에 필요한 최소한의 시스템 패키지만 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 의존성 설치 (캐시 최적화를 위해 lock 파일 먼저 복사)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-cache

# ---------------------------------------------------
# 2단계: Production stage (최종 실행 이미지)
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app

# 실행 시 필요한 런타임 라이브러리만 설치 (build-essential 제외)
RUN apt-get update && apt-get install -y \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# 빌드 단계에서 생성된 가상환경(.venv)만 통째로 복사
COPY --from=builder /app/.venv /app/.venv
# 소스 코드 복사
COPY . .

# 환경변수 설정
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# 이미 venv 내부에 패키지가 있으므로 python으로 직접 실행하거나 uv run 사용
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]