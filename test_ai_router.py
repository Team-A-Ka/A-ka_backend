import sys
import logging
from app.tasks.router_tasks import process_ai_routing_task

logging.basicConfig(level=logging.INFO)


def run_test():
    print("================== Test 1: Upload (유튜브 링크) ==================")
    res1 = process_ai_routing_task(
        "tester_1",
        "이거 요약해서 올려줄래? https://www.youtube.com/watch?v=HbYF0EkAvAo",
    )
    print(f"Result 1: {res1}\n")

    # print("================== Test 2: Search (일반 질문 검색) ==================")
    # res2 = process_ai_routing("tester_2", "어제 뉴스에서 말한 이슈 뭐 있었지?")
    # print(f"Result 2: {res2}\n")

    # print("================== Test 3: Unknown (일상 대화) ==================")
    # res3 = process_ai_routing("tester_3", "날씨 좋은데 밖에 나갈까?")
    # print(f"Result 3: {res3}\n")


if __name__ == "__main__":
    run_test()
