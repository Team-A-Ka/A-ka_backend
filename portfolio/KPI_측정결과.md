# A-KA KPI 측정 결과

> 모델: chat=`gemini-2.5-flash-lite` / embed=`gemini-embedding-001` (1536d)
> 측정 시작: 2026-06-04T22:08:57
> 환경: Windows 11 · Python 3.12 · Celery 5.6.3 (solo pool) · pgvector

---

## 📊 UPLOAD 파이프라인 요약 — 1차 측정 (2026-06-04)

| 영상 | 청크 | 임베딩 | 총 시간 | LLM 호출 | Input 토큰 | Output 토큰 | 비용 (USD) |
|---|---|---|---|---|---|---|---|
| **5분** (o58i, 물티슈 성분) | 38 | 38 | **12.3s** | 40 | 40,770 | 3,349 | **$0.0054** |
| **20분** (F9dSJm) | 48 | 48 | **14.2s** | 50 | 52,073 | 4,431 | **$0.0070** |
| **60분** (-A9RxJn) | 72 | 72 | **17.2s** | 74 | 80,406 | 5,387 | **$0.0102** |
| **합계** | 158 | 158 | — | 164 | 173,249 | 13,167 | **$0.0226** |

**관찰**:
- **청크 수가 영상 길이에 sub-linear** — semantic chunking 효과 (5분:38 / 20분:48 / 60분:72, 분당 7.6→2.4→1.2 청크)
- **총 시간 ≈ 청크 수에 비례** (1분당 시간이 아닌) — ThreadPoolExecutor(max_workers=10) 병렬화로 영상 길이에 거의 둔감
- **호출당 비용 ~$0.00014로 일정** — 청크 수만 알면 비용 정확 예측 가능
- **60분 영상이 12배 길지만 처리 시간 1.4배** — *"콘텐츠 길이와 무관하게 거의 일정한 처리 시간"* 포트폴리오 어필 포인트

**단계별 분해 (대표값)**:
| 단계 | 5분 | 20분 | 60분 |
|---|---|---|---|
| Step1 (collect+chunk) | 3.0s | 2.1s | 2.1s |
| Step2 (요약+임베딩+overview) | ~7s | ~10s | ~13s |
| Step3 (publish) | 2s | 2s | 1s |

---

## 📑 상세 측정 로그 (이하 JSON)



## SEARCH — sanity-check

```json
{
  "label": "sanity-check",
  "query": "물티슈 보존제가 위험해?",
  "elapsed_s": 2.45,
  "ok": true,
  "error": null,
  "answer_len": 336,
  "answer_preview": "물티슈에 보존재가 없으면 오히려 문제가 될 수 있으며, 안전성 평가를 거쳐 보편적으로 사용되는 소듐벤조에이트나 카프릴릴글라이콜과 같은 보존재는 적정량 사용이 필수적입니다. 이러한 보존재를 사용하지 않는 것이 더 위험할 수 있습니다. [출처 1, 2]\n\n물티슈 성분 중 유해 물질은 없으며, 공포 마케팅은 특정 브랜드 매출 증대를 위한 수단으로 활용됩니다. 오…",
  "sources_count": 0,
  "chunks_used": 5,
  "model_chat": "gemini-2.5-flash-lite",
  "model_embed": "gemini-embedding-001",
  "langsmith": {
    "llm_calls": 0,
    "embedding_calls": 0,
    "input_tokens": 0,
    "output_tokens": 0,
    "total_runs_seen": 1
  },
  "cost_total_usd": 0.0,
  "measured_at": "2026-06-04T22:08:57"
}
```

## SEARCH — sanity-check-v2

```json
{
  "label": "sanity-check-v2",
  "query": "물티슈 보존제가 위험해 다시",
  "elapsed_s": 2.79,
  "ok": true,
  "error": null,
  "answer_len": 231,
  "answer_preview": "물티슈에 보존재가 없으면 오히려 문제가 될 수 있으며, 보존재는 꼭 필요한 물질 중 하나입니다. 소듐벤조에이트나 카프릴릴글라이콜처럼 안전성 평가를 거쳐 보편적으로 사용되는 보존재는 오히려 사용하지 않는 것이 더 위험할 수 있습니다. 유럽 식품 안전청(EFSA)은 물티슈 성분 관련 연구가 발암 입증에 부족하다고 결론 내렸습니다. 따라서 현재까지의 결과로는 크…",
  "sources_count": 0,
  "chunks_used": 5,
  "model_chat": "gemini-2.5-flash-lite",
  "model_embed": "gemini-embedding-001",
  "langsmith": {
    "llm_calls": 1,
    "embedding_calls": 0,
    "input_tokens": 2442,
    "output_tokens": 378,
    "total_runs_seen": 6,
    "run_type_counts": {
      "chain": 5,
      "llm": 1
    }
  },
  "cost_total_usd": 0.00039540000000000007,
  "measured_at": "2026-06-04T22:10:12"
}
```

## UPLOAD — 5분 영상 (o58i, 물티슈 성분)

```json
{
  "label": "5분 영상 (o58i, 물티슈 성분)",
  "url": "https://www.youtube.com/watch?v=o58i-LcqxVE",
  "video_id": "o58i-LcqxVE",
  "title": "물티슈 성분 안전성, 화학적 관점에서 분석",
  "category": "과학",
  "model_chat": "gemini-2.5-flash-lite",
  "model_embed": "gemini-embedding-001",
  "embed_dim": 1536,
  "total_wall_s": 12.97,
  "chunks": 38,
  "embeddings": 38,
  "summary_len": 182,
  "step_durations_s": {
    "step1_chunking": 1.0,
    "step2_chunk_summary": 5.0,
    "step2_embedding": 1.0,
    "step2_overview": 2.0,
    "step3_publish": 0.0
  },
  "estimated_llm_calls": 40,
  "estimated_embedding_calls": 1,
  "events": {
    "chunk_summary_failed": 2,
    "overview_failed": 0,
    "embedding_block_done": 1,
    "any_429": 0
  },
  "langsmith": {
    "llm_calls": 40,
    "embedding_calls": 0,
    "input_tokens": 40770,
    "output_tokens": 3349,
    "total_runs_seen": 48,
    "run_type_counts": {
      "parser": 2,
      "llm": 40,
      "chain": 6
    }
  },
  "cost_input_usd": 0.004077,
  "cost_output_usd": 0.0013396,
  "cost_total_usd": 0.0054166,
  "transitions": [
    [
      0.2526264190673828,
      "PENDING",
      0,
      0,
      0
    ],
    [
      3.262312173843384,
      "PENDING",
      38,
      0,
      0
    ],
    [
      10.288421154022217,
      "PENDING",
      38,
      38,
      182
    ],
    [
      12.298829317092896,
      "COMPLETED",
      38,
      38,
      182
    ]
  ],
  "measured_at": "2026-06-04T22:11:09"
}
```

## UPLOAD — 20분 영상 (F9dSJm)

```json
{
  "label": "20분 영상 (F9dSJm)",
  "url": "https://www.youtube.com/watch?v=F9dSJm2VPGk",
  "video_id": "F9dSJm2VPGk",
  "title": "미국 마리화나 규제 완화와 의료용 대마의 화학적 작용",
  "category": "과학",
  "model_chat": "gemini-2.5-flash-lite",
  "model_embed": "gemini-embedding-001",
  "embed_dim": 1536,
  "total_wall_s": 14.57,
  "chunks": 48,
  "embeddings": 48,
  "summary_len": 142,
  "step_durations_s": {
    "step1_chunking": 2.0,
    "step2_chunk_summary": 6.0,
    "step2_embedding": 1.0,
    "step2_overview": 2.0,
    "step3_publish": 0.0
  },
  "estimated_llm_calls": 50,
  "estimated_embedding_calls": 1,
  "events": {
    "chunk_summary_failed": 3,
    "overview_failed": 0,
    "embedding_block_done": 1,
    "any_429": 0
  },
  "langsmith": {
    "llm_calls": 50,
    "embedding_calls": 0,
    "input_tokens": 52073,
    "output_tokens": 4431,
    "total_runs_seen": 58,
    "run_type_counts": {
      "parser": 2,
      "llm": 50,
      "chain": 6
    }
  },
  "cost_input_usd": 0.005207300000000001,
  "cost_output_usd": 0.0017724000000000001,
  "cost_total_usd": 0.006979700000000001,
  "transitions": [
    [
      0.10174012184143066,
      "PENDING",
      0,
      0,
      0
    ],
    [
      2.1101207733154297,
      "PENDING",
      48,
      0,
      0
    ],
    [
      12.151211500167847,
      "PENDING",
      48,
      48,
      142
    ],
    [
      14.15700364112854,
      "COMPLETED",
      48,
      48,
      142
    ]
  ],
  "measured_at": "2026-06-04T22:15:35"
}
```

## UPLOAD — 60분 영상 (-A9RxJn)

```json
{
  "label": "60분 영상 (-A9RxJn)",
  "url": "https://www.youtube.com/watch?v=-A9RxJn5V2o",
  "video_id": "-A9RxJn5V2o",
  "title": "이종범 작가, '장송의 프리렌' 명작 판타지 만화 분석",
  "category": "뉴스",
  "model_chat": "gemini-2.5-flash-lite",
  "model_embed": "gemini-embedding-001",
  "embed_dim": 1536,
  "total_wall_s": 17.58,
  "chunks": 72,
  "embeddings": 72,
  "summary_len": 190,
  "step_durations_s": {
    "step1_chunking": 1.0,
    "step2_chunk_summary": 9.0,
    "step2_embedding": 1.0,
    "step2_overview": 2.0,
    "step3_publish": 0.0
  },
  "estimated_llm_calls": 74,
  "estimated_embedding_calls": 1,
  "events": {
    "chunk_summary_failed": 5,
    "overview_failed": 0,
    "embedding_block_done": 1,
    "any_429": 0
  },
  "langsmith": {
    "llm_calls": 74,
    "embedding_calls": 0,
    "input_tokens": 80406,
    "output_tokens": 5387,
    "total_runs_seen": 81,
    "run_type_counts": {
      "chain": 6,
      "llm": 74,
      "parser": 1
    }
  },
  "cost_input_usd": 0.0080406,
  "cost_output_usd": 0.0021548,
  "cost_total_usd": 0.0101954,
  "transitions": [
    [
      0.09998750686645508,
      "PENDING",
      0,
      0,
      0
    ],
    [
      2.1058146953582764,
      "PENDING",
      72,
      0,
      0
    ],
    [
      15.16130781173706,
      "PENDING",
      72,
      0,
      190
    ],
    [
      16.1690354347229,
      "PENDING",
      72,
      72,
      190
    ],
    [
      17.171313524246216,
      "COMPLETED",
      72,
      72,
      190
    ]
  ],
  "measured_at": "2026-06-04T22:16:14"
}
```
