---
title: "Qdrant — 벡터 데이터베이스가 일반 DB와 다른 점"
description: "의미 기반 검색에 쓰는 벡터 DB Qdrant의 컬렉션 설계, user_id 필터, score_threshold 동작을 코드와 함께 정리"
date: "2026-10-05"
tags: ["데이터베이스"]
qa_done: true
rewritten: true
---

PostgreSQL은 "사과랑 비슷한 과일 찾아줘" 같은 의미 기반 검색을 못 해
정확히 일치하는 텍스트만 찾기 때문이야
ElasticSearch는 키워드 검색에 강하지만 벡터 검색은 후발주자라 설정이 복잡하고 무거운 편이야

Qdrant는 벡터 유사도 검색 전용 DB야
HNSW 인덱스로 빠르게 근사 최근접 탐색을 하고, 페이로드 필터링으로 "이 유저의 메모리 중 유사한 것"까지 한 번에 찾을 수 있어

## 용어부터 정리

- 벡터: 텍스트를 수백~수천 차원의 숫자 배열로 바꾼 것, 의미가 비슷한 텍스트는 벡터 공간에서 가까워
- 임베딩: 텍스트를 벡터로 바꾸는 과정, 또는 그 결과
- 코사인 유사도: 두 벡터 사이의 각도로 유사도를 재는 방식, 방향이 같을수록 1에 가까워
- HNSW: Qdrant가 쓰는 벡터 인덱스 알고리즘
- 컬렉션: Qdrant의 테이블, 같은 차원의 벡터들을 저장해
- 포인트: 컬렉션 안의 한 레코드, id + vector + payload로 구성돼
- 페이로드: 포인트에 붙이는 메타데이터 dict, 필터링에 쓰여

## RDB 검색과 뭐가 다른가

```
PostgreSQL  WHERE content = '운동'
            → 정확히 일치하는 행만 반환

Qdrant      '운동' 쿼리 벡터
            → '헬스장 다님', '조깅 좋아함' 처럼 의미가 가까운 것을 반환
```

JARVIS의 메모리 검색은 이런 흐름이야

```
user_message: '내일 약속 잡자'
  → embed (text-embedding-3-small)
  → 1536차원 쿼리 벡터
  → Qdrant query_points
  → user_id 필터 (내 메모리만)
  → score >= 0.7 필터
  → 상위 5개 반환
  → Claude 시스템 프롬프트에 주입
```

## 컬렉션 생성

공식 예제는 이렇게 단순해

```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

client = QdrantClient(url="http://localhost:6333")

client.create_collection(
    collection_name="my_collection",
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)
```

JARVIS 실제 코드는 몇 가지가 달라

```python
MEMORIES_COLLECTION = "memories"

async def ensure_collection() -> None:
    try:
        qdrant = get_qdrant_client()
        if not await qdrant.collection_exists(MEMORIES_COLLECTION):
            try:
                await qdrant.create_collection(
                    collection_name=MEMORIES_COLLECTION,
                    vectors_config=VectorParams(size=EMBEDDING_DIMENSIONS, distance=Distance.COSINE),
                )
            except Exception:
                # 다른 프로세스가 동시에 생성한 경우, 이미 존재하면 무시
                if not await qdrant.collection_exists(MEMORIES_COLLECTION):
                    raise

        # user_id 필드 인덱스 생성으로 필터 성능 향상
        await qdrant.create_payload_index(
            collection_name=MEMORIES_COLLECTION,
            field_name="user_id",
            field_schema=PayloadSchemaType.KEYWORD,
        )
    except Exception as exc:
        _log.warning("ensure_collection failed at startup: %s", exc)
```

달라진 부분은 세 가지야

- `AsyncQdrantClient`를 써서 FastAPI의 async 환경과 맞췄어
- `user_id` 필터가 많아서 `create_payload_index`로 KEYWORD 인덱스를 걸었어
- lifespan에서 앱 시작 시 한 번만 호출해

## 포인트 추가 (upsert)

```python
await qdrant.upsert(
    collection_name=MEMORIES_COLLECTION,
    points=[
        PointStruct(
            id=str(uuid.uuid4()),      # 문자열 UUID
            vector=embedding_vector,   # list[float], 1536차원
            payload={
                "user_id": user_id,
                "content": memory_content,
                "category": "PREFERENCE",
            },
        )
    ],
)
```

벡터와 함께 `user_id`, `content`, `category` 같은 메타데이터를 payload로 붙여두는 게 핵심이야
나중에 이 payload로 필터링해

## 유사도 검색 + 필터 (query_points)

공식 예제는 쿼리 벡터와 limit만 넘겨

```python
results = client.query_points(
    collection_name="my_collection",
    query=[0.1, 0.2, ...],
    limit=5,
)
```

JARVIS는 유저별로 메모리를 격리해야 해서 필터를 붙였어

```python
response = await qdrant.query_points(
    collection_name=MEMORIES_COLLECTION,
    query=vector,                    # embed(user_message) 결과
    query_filter=Filter(
        must=[
            FieldCondition(
                key="user_id",
                match=MatchValue(value=request.user_id),  # 이 유저의 메모리만
            )
        ]
    ),
    limit=cfg.qdrant_top_k,                       # 기본 5개
    score_threshold=cfg.qdrant_score_threshold,   # 기본 0.7 이상만
    with_payload=True,                            # payload 포함해서 반환
)
results = response.points
```

`query_filter`의 `must` 조건 덕분에 다른 유저의 메모리는 결과에 섞이지 않아
`with_payload=True`를 빼면 id와 score만 돌아오니까, 메모리 내용을 쓰려면 꼭 필요해

## Filter 조건 종류

| 조건 | 의미 | 예시 |
|------|------|------|
| `must` | AND, 모든 조건 충족 | user_id 일치 AND category 일치 |
| `should` | OR, 하나 이상 충족 | category가 FACT OR PREFERENCE |
| `must_not` | NOT, 조건 제외 | category가 EVENT 아닌 것만 |

```python
# user_id 필터 + FACT 카테고리만
Filter(
    must=[
        FieldCondition(key="user_id", match=MatchValue(value=user_id)),
        FieldCondition(key="category", match=MatchValue(value="FACT")),
    ]
)
```

`MatchValue`는 정확히 일치하는 값을 찾을 때 쓰고, KEYWORD 인덱스와 짝으로 동작해
user_id처럼 enum 비슷한 문자열 값에 잘 맞아

## score_threshold가 하는 일

```
벡터 유사도 스코어
  1.0  동일한 의미
  0.9  매우 유사
  0.7  어느 정도 관련  ← 임계값
  0.5  낮은 관련성
  0.0  전혀 무관
```

임계값 아래면 아예 반환하지 않아
관련 없는 메모리가 Claude 컨텍스트를 낭비하는 걸 막아주는 장치야

## 놓치기 쉬운 함정

❌ FastAPI에서 동기 `QdrantClient` 사용
이벤트 루프를 block해

✅ `AsyncQdrantClient` 사용
`await`로 호출해서 async 환경과 맞춰

그 밖에 알아둘 것들이야

- `create_payload_index`는 중복 호출해도 무해해, 이미 있으면 에러 없이 무시되니까 lifespan에서 매번 불러도 돼
- 여러 인스턴스가 동시에 컬렉션을 만들려 하면 에러가 날 수 있어, `try/except` 뒤에 `collection_exists`를 다시 확인하는 식으로 처리해
- `score_threshold`는 튜닝이 필요해, 0.7은 실험값이고 메모리 내용이 짧으면 유사도가 낮게 나올 수 있어
- 컬렉션을 `size=1536`으로 만들었는데 768차원 같은 다른 임베딩 모델을 쓰면 벡터 차원 불일치로 에러가 나
