"""Gemini embedding smoketest — verify key + model + dim=1536 via langchain wrapper."""
import sys, os, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.core.config import settings

key = settings.GOOGLE_API_KEY
print(f"GOOGLE_API_KEY = {key[:10]}...{key[-6:]} (len={len(key)})")
print(f"GEMINI_MODEL   = {settings.GEMINI_MODEL}")

# Try gemini-embedding-001 first (Matryoshka, supports output_dimensionality)
from langchain_google_genai import GoogleGenerativeAIEmbeddings

CANDIDATES = [
    ("gemini-embedding-001", 1536),  # 옵션 D 핵심 — Matryoshka 1536
    ("models/text-embedding-004", 768),  # fallback
]

for model, target_dim in CANDIDATES:
    print(f"\n--- Trying model={model} (target_dim={target_dim}) ---")
    try:
        # output_dimensionality는 langchain wrapper에선 task_type/output_dimensionality 인자로 들어감
        kwargs = {"model": model, "google_api_key": key}
        if target_dim != 768:  # text-embedding-004는 768 고정
            kwargs["output_dimensionality"] = target_dim
        emb = GoogleGenerativeAIEmbeddings(**kwargs)
        t0 = time.time()
        vec = emb.embed_query("A-KA 포트폴리오 Gemini 임베딩 검증용 문장입니다.")
        dt = time.time() - t0
        print(f"  OK  dim={len(vec)}  elapsed={dt:.2f}s")
        if len(vec) == target_dim:
            print(f"  *** SUCCESS: model={model} returns dim={target_dim} ***")
            break
    except Exception as e:
        print(f"  FAIL: {type(e).__name__}: {e}")
        traceback.print_exc(limit=2)
