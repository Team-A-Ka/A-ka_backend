from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm import get_chat_model_primary


class CategoryResolution(BaseModel):
    category_name: str = Field(description="최종 저장할 카테고리명")
    reason: str = Field(description="선택 이유")


_category_chain = None


def _get_category_chain():
    global _category_chain
    if _category_chain is None:
        _category_chain = get_chat_model_primary().with_structured_output(
            CategoryResolution,
        )
    return _category_chain


def normalize_category_name(category_name: str | None) -> str:
    name = (category_name or "").strip().replace(" ", "")
    return name or "미분류"


def resolve_category_name(
    raw_category: str | None,
    title: str,
    summary: str,
    existing_categories: list[str],
) -> str:
    normalized_raw = normalize_category_name(raw_category)

    try:
        parsed = _get_category_chain().invoke(
            [
                SystemMessage(
                    content=(
                        "너는 영상 요약 서비스의 카테고리 정규화 담당자다. "
                        "카테고리는 영상의 형식이 아니라 핵심 주제로 정한다. "
                        "'교육', '강의', '입문', '튜토리얼', '기술교육'처럼 형식이나 난이도를 "
                        "나타내는 카테고리는 피한다.\n\n"
                        # ── 우산(umbrella) 우선 원칙 ────────────────────────
                        "[우산 우선 원칙]\n"
                        "기존 카테고리가 그 영상의 주제를 포괄할 수 있다면, 좁은 새 카테고리를 만들기보다 "
                        "기존 우산 카테고리에 합류시킨다. 유사 주제가 여러 좁은 이름으로 분산되면 "
                        "검색·재조회 품질이 떨어진다. 약간 넓은 범주에 묶이는 것이 분산보다 낫다.\n\n"
                        # ── 패턴 학습용 seed 예시 ────────────────────────
                        "[합류 패턴 예시]\n"
                        "- 화학·물리·생물·뇌과학·천문·기후 → '과학'\n"
                        "- 군사·정치·범죄·시사·사건사고·재난 → '사회문제'\n"
                        "- 헬스·요가·필라테스·스포츠·다이어트 → '운동'\n"
                        "- 양식·한식·디저트·카페·먹방 → '맛집'\n"
                        "- 파이썬·C·백엔드·API·프레임워크·CS → '프로그래밍'\n"
                        "- 노래·MV·커버·작곡·악기·콘서트 → '음악'\n"
                        "- 주식·코인·부동산·경제·재무 → '재테크'\n\n"
                        # ── 새 카테고리 생성 조건 ────────────────────────
                        "[새 카테고리 생성 조건]\n"
                        "기존 카테고리 어느 우산에도 합리적으로 들어가지 않을 때만 새로 만든다. "
                        "만들 때는 1~5자의 간결한 명사 + 충분히 넓은 우산이 되도록 한다. "
                        "좋은 예: '음악', '여행', '영화'. 나쁜 예: '발라드', '제주여행', 'SF영화'. "
                        "기존 카테고리가 형식 중심 이름이면(예: '강의') 그 안에 합류시키지 말고 "
                        "주제 중심 우산을 새로 만들거나 다른 기존 우산에 합류시킨다."
                    ),
                ),
                HumanMessage(
                    content=(
                        f"기존 카테고리 목록: {existing_categories}\n"
                        f"처음 생성된 카테고리: {normalized_raw}\n"
                        f"영상 제목: {title}\n"
                        f"영상 요약: {summary}\n"
                        "최종 저장할 카테고리를 하나만 결정해줘."
                    ),
                ),
            ],
        )
        if isinstance(parsed, dict):
            parsed = CategoryResolution.model_validate(parsed)
        resolved = parsed.category_name
        return normalize_category_name(resolved)
    except Exception:
        return normalized_raw
