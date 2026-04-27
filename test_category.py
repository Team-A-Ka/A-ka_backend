import logging
from openai import OpenAI
from app.core.config import settings
from app.schemas.graph_state import VideoOverview

logging.basicConfig(level=logging.INFO)
openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)

def test_category_classification(text: str, test_name: str):
    print(f"\n==============================================")
    print(f"테스트 케이스: {test_name}")
    print(f"입력 텍스트: {text[:50]}...")
    print(f"----------------------------------------------")
    
    try:
        response = openai_client.beta.chat.completions.parse(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "아래는 유튜브 영상의 요약 내용이야. "
                        "이 내용을 종합하여 영상 전체 제목, 전체 요약, 카테고리를 생성해."
                    ),
                },
                {"role": "user", "content": text},
            ],
            response_format=VideoOverview,
        )
        overview = response.choices[0].message.parsed
        print(f"✅ 판별된 카테고리 : [{overview.category}]")
        print(f"✅ 생성된 제목     : {overview.title}")
        print(f"✅ 통합 요약       : {overview.full_summary}")
    except Exception as e:
        print(f"에러 발생: {e}")

if __name__ == "__main__":
    # Case 1: 기존 11개 중 하나에 명확히 들어맞는 경우
    text_random = (
        "오늘은 정말 맛있는 돼지고기 김치찌개 황금 레시피를 알려드리겠습니다. "
        "묵은지를 참기름에 달달 볶다가 돼지고기 목살을 듬뿍 넣고 사골 육수를 부어 끓입니다. "
        "마지막에 대파와 청양고추를 송송 썰어 넣으면 밥 두 공기는 뚝딱입니다."
    )
    test_category_classification(text_random, "기본 카테고리 매칭 (기대값: 요리 또는 맛집)")

    # Case 2: 11개(요리, 운동, 자동차, 공부, 게임, 동물, 메이크업, 맛집, 뉴스, 예능, 재테크)에 없는 경우
    text_science = (
        "양자역학에서 슈뢰딩거의 고양이는 매우 유명한 사고 실험입니다. "
        "상자 안의 고양이는 관측되기 전까지 살아있는 상태와 죽어있는 상태가 중첩(Superposition)되어 있습니다. "
        "이는 미시 세계의 입자가 가지는 파동 함수의 붕괴를 설명하기 위해 고안되었습니다."
    )
    test_category_classification(text_science, "새로운 카테고리 동적 생성 (기대값: 과학, 물리 등)")
