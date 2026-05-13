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
                        "나타내는 카테고리는 피한다. "
                        "기존 카테고리 중 의미가 같은 것이 있으면 기존 카테고리명을 그대로 사용한다. "
                        "다만 기존 카테고리가 형식 중심 이름이면 실제 주제에 맞는 새 카테고리를 만든다. "
                        "예를 들어 파이썬, C언어, 백엔드, API, 프레임워크 개발 내용은 "
                        "'프로그래밍'이 더 적절하다. "
                        "정말 맞는 기존 카테고리가 없을 때만 새 카테고리를 만들고, "
                        "새 카테고리는 1~5자의 간결한 명사로 작성한다."
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
