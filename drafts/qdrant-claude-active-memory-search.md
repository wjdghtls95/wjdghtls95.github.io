---
title: "Qdrant + Claude — 능동적 메모리 검색 구현하기"
description: "자동 RAG는 검색 시점과 쿼리를 결정 못한다, Tool Use로 Claude가 직접 판단하게 만든 구조"
date: "2026-09-02"
tags: ["AI"]
qa_done: true
rewritten: true
---

자동 RAG는 메시지가 오면 무조건 검색부터 한다

```
유저: "오늘 뭐 먹을까?"
코드: embed("오늘 뭐 먹을까?") → Qdrant 검색
→ "오늘 뭐 먹을까?"라는 대화 의도 자체를 벡터화
→ "음식 선호" 쿼리가 아니라서 검색 결과가 최적이 아님
```

검색할지 말지, 뭘 검색할지를 Claude가 직접 정하지 않고 코드가 유저 메시지를 그대로 쿼리로 써버리는 게 문제다

JARVIS는 이 부분을 Anthropic Tool Use로 채웠다

Claude가 "메모리가 필요한가"부터 "어떤 키워드로 검색할까"까지 직접 판단하고, 실제 벡터 검색은 Qdrant가 실행하는 구조다

## 어떻게 동작하나

역할을 나누면 이렇다

| 역할 | 담당 |
|---|---|
| 언제 메모리가 필요한지 판단 | Claude (Tool Use) |
| 어떤 키워드로 검색할지 결정 | Claude (Tool Use) |
| 실제 의미 기반 검색 실행 | Qdrant |
| 검색 결과를 Claude에게 전달 | tool_result |

흐름은 2라운드다

- Round 1 — Claude에게 tool 스펙을 전달, Claude가 필요하다고 판단하면 `tool_use` 이벤트로 검색 쿼리를 반환
- 서버가 그 쿼리로 Qdrant 벡터 검색 실행
- Round 2 — 검색 결과를 `tool_result`로 Claude에게 다시 전달, 최종 답변 생성

### Tool 정의

이름은 임의로 지어도 되고, Claude가 실제로 읽고 판단하는 건 description이다

```python
SEARCH_MEMORY_TOOL: dict = {
    "name": "search_memory",
    "description": (
        "유저의 장기 메모리에서 특정 주제 정보를 검색합니다. "
        "유저의 선호·습관·과거 경험이 필요할 때 사용합니다. "
        "단순 인사나 일반 대화에서는 사용하지 말 것."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "검색할 내용 — 구체적 키워드로 (예: '음식 선호', '운동 루틴')",
            },
        },
        "required": ["query"],
    },
}
```

### Round 1 — tool_use 이벤트 받기

```python
async with claude.messages.stream(
    model="claude-sonnet-4-6",
    messages=messages,
    tools=[SEARCH_MEMORY_TOOL],
) as stream:
    async for event in stream:
        if event.type == "content_block_start" and event.content_block.type == "tool_use":
            tool_id   = event.content_block.id    # "toolu_abc123"
            tool_name = event.content_block.name  # "search_memory"

        elif event.type == "content_block_delta" and is_tool_block:
            current_tool_input += event.delta.partial_json

        elif event.type == "content_block_stop" and is_tool_block:
            parsed_input = json.loads(current_tool_input)
            yield f"data: {json.dumps({'type': 'tool_use', 'id': tool_id, 'name': tool_name, 'input': parsed_input})}\n\n"
```

Claude가 파라미터를 JSON으로 조각조각 스트리밍하기 때문에 `content_block_delta`에서 이어붙이고, `content_block_stop`에서 완성된 input을 파싱한다

### Qdrant 검색 실행

Claude가 만든 쿼리를 그대로 임베딩해서 검색한다

```python
query = parsed_input["query"]   # "음식 선호 식습관" — Claude가 직접 최적화한 쿼리

vector = await embed(query)

results = await qdrant.query_points(
    collection_name=MEMORIES_COLLECTION,
    query=vector,
    query_filter=Filter(
        must=[FieldCondition(key="user_id", match=MatchValue(value=user_id))]
    ),
    limit=5,             # top_k
    score_threshold=0.7, # 유사도 0.7 미만 제외
    with_payload=True,
)
# → ["삼겹살 좋아함", "단골 고깃집 있음", "매운 음식 선호"]
```

### Round 2 — 검색 결과 다시 넣기

```python
round2_messages = base_messages + [
    {
        "role": "assistant",
        "content": [{
            "type": "tool_use",
            "id": tool_id,              # Round 1에서 받은 id — 반드시 일치해야 함
            "name": "search_memory",
            "input": parsed_input,
        }]
    },
    {
        "role": "user",
        "content": [{
            "type": "tool_result",
            "tool_use_id": tool_id,     # 이 id로 Round 1과 매칭
            "content": json.dumps(results, ensure_ascii=False)
        }]
    }
]

async with claude.messages.stream(
    model="claude-sonnet-4-6",
    messages=round2_messages,
    tools=None,  # Round 2에서는 tool 비활성화
) as stream:
    ...
```

❌ Round 2에서도 `tools=[SEARCH_MEMORY_TOOL]`를 그대로 넘기면 Claude가 또 tool_use를 요청할 수 있어서 무한 루프 위험이 생긴다
✅ `tools=None if is_round2 else [SEARCH_MEMORY_TOOL]`로 Round 2에서는 확실히 꺼야 한다

## 자동 RAG와 뭐가 다른가

둘 다 Qdrant를 쓰지만 차이는 Claude가 검색 전에 개입하느냐다

```
자동 RAG:
  유저 메시지 → embed → Qdrant → 프롬프트 주입 → Claude 호출
  (Claude가 관여하기 전에 검색이 끝남)

Tool Use + Qdrant:
  유저 메시지 → Claude 호출(Round 1) → Claude가 쿼리 결정
             → Qdrant 검색 → Claude에게 결과 전달(Round 2) → Claude 답변
```

메모리가 적을 때는 이 차이가 잘 안 보인다

메모리가 수천 개로 늘어나면 쿼리 정밀도 차이가 검색 결과 품질에 바로 영향을 준다

언제 도입할지 기준을 정리하면

| 상황 | 권장 방식 |
|---|---|
| 메모리 < 수백 개 | 자동 RAG로 충분 |
| 메모리 수백~수천 개 | 조합 방식 고려 시점 |
| 메모리 수천 개 이상 | 조합 방식 필요 |
| 여러 주제 메모리를 한 번에 | 조합 방식만 가능 (다중 쿼리) |
| "기억을 못 하는 것 같다" 피드백 반복 | 도입 신호 |

## 삽질한 것

Round 2에서 tool을 안 끄면 무한 루프가 생긴다

Round 2에도 tools를 넘기면 Claude가 tool_result를 보고도 또 tool_use를 요청할 수 있다
해결은 `is_round2`일 때 `tools=None`으로 명시적으로 끄는 것

tool_use_id는 Round 1과 Round 2에서 반드시 같은 값이어야 한다

Round 2의 `tool_result.tool_use_id`가 Round 1의 `tool_use.id`와 다르면 Claude가 매칭에 실패한다
Round 1에서 받은 id를 그대로 재사용해야지, 새로 생성하면 안 된다

자동 RAG와 이 조합 방식을 동시에 켜두면 같은 메모리가 두 번 주입된다

둘 다 같은 Qdrant 컬렉션을 검색하기 때문인데, messages를 조립할 때 memory_id 기준으로 중복 제거하는 단계가 필요하다

용어 정리

- search_memory: 함수 이름은 임의, Claude는 description을 읽고 호출 여부를 판단
- tool_use_id: Round 1의 tool_use와 Round 2의 tool_result를 연결하는 식별자
- score_threshold: Qdrant 검색에서 이 유사도 미만은 버리는 필터 (JARVIS는 0.7)
