import sys
import logging
from app.services.router_service import analyze_intent_and_route

logging.basicConfig(level=logging.INFO)

def run_test():
    print("================== Test 1: Upload (유튜브 링크) ==================")
    res1 = analyze_intent_and_route('tester_1', '이거 요약해서 올려줄래? https://www.youtube.com/watch?v=dQw4w9WgXcQ')
    print(f"Result 1: {res1}\n")

    print("================== Test 2: Search (일반 질문 검색) ==================")
    res2 = analyze_intent_and_route('tester_2', '어제 본 영상에서 FastAPI가 뭐라고 했지?')
    print(f"Result 2: {res2}\n")

    print("================== Test 3: Unknown (일상 대화) ==================")
    res3 = analyze_intent_and_route('tester_3', '안뇽 오늘 날씨 짱이네')
    print(f"Result 3: {res3}\n")

if __name__ == '__main__':
    run_test()
