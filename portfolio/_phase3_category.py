import sys
sys.path.insert(0, ".")
from app.services.category_resolver import normalize_category_name, resolve_category_name

print("===== normalize_category_name (LLM 없음) =====")
cases = [("  과 학  ", "과학"), ("", "미분류"), (None, "미분류"), ("재테크", "재테크")]
for raw, expect in cases:
    got = normalize_category_name(raw)
    print(f"  {raw!r:12} -> {got!r:8} (기대 {expect!r}) {'OK' if got==expect else 'FAIL'}")

print("\n===== resolve_category_name (LLM 우산 정규화) =====")
existing = ["과학", "만화"]

# 1) 기존 우산 합류: 화학 주제 → 과학
r1 = resolve_category_name("화학", "산-염기 반응의 원리",
                           "산과 염기의 중화 반응과 pH를 화학적으로 설명한다.", existing)
print(f"  [기존우산] raw=화학 / existing={existing} -> {r1!r}  (기대 '과학')")

# 2) 신규 우산 생성: 여행 주제 → 기존(과학/만화)에 없으니 새 우산
r2 = resolve_category_name("제주여행", "제주도 3박4일 여행 코스",
                           "제주 동부 해안과 오름, 맛집을 도는 여행 일정 소개.", existing)
print(f"  [신규우산] raw=제주여행 / existing={existing} -> {r2!r}  (기대: 과학·만화 아닌 넓은 우산, 예 '여행')")

# 3) 형식 이름 회피: 강의 → 주제 우산으로
r3 = resolve_category_name("강의", "파이썬 비동기 입문",
                           "asyncio로 코루틴과 이벤트 루프를 다루는 백엔드 강의.", existing)
print(f"  [형식회피] raw=강의 / existing={existing} -> {r3!r}  (기대: '강의' 아닌 주제우산, 예 '프로그래밍')")
