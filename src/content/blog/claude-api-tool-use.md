---
title: "Claude API Tool Use — AI가 직접 함수를 호출하게 만들기"
description: "Claude API Tool Use — AI가 직접 함수를 호출하게 만들기"
date: "2026-09-19"
tags: ["AI"]
qa_done: true
rewritten: true
---

## 왜 필요한가

LLM은 텍스트만 생성할 수 있다
캘린더를 직접 조회하거나 DB를 조회할 수 없다

Tool Use는 모델이 "이 함수를 실행해달라"고 요청하는 방식이다
서버가 함수를 실행하고 결과를 다시 모델에게 전달하면, 모델이 그 결과로 최종 답변을 생성한다

JARVIS AI에서는 `get_free_slots` 툴로 캘린더 빈 시간을 조회하는 데 쓴다

## 어떻게 동작하나

흐름은 세 단계다

Round 1에서 모델이 응답 대신 "이 함수 호출해줘"라고 요청한다
서버가 그 함수를 실행한다
Round 2에서 실행 결과를 `tool_result`로 주입하면 모델이 최종 답변을 생성한다

### 1단계 — Tool 정의

JSON Schema 형식으로 함수 스펙을 정의한다
`name`, `description`, `input_schema`가 필수고, Claude는 description을 보고 언제 이 툴을 써야 하는지 판단한다

```python
GET_FREE_SLOTS_TOOL: dict = {
    "name": "get_free_slots",
    "description": "사용자의 캘린더에서 가능한 빈 시간대를 조회합니다. 일정 조율이나 미팅 시간 제안이 필요할 때 사용합니다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "from": {
                "type": "string",
                "description": "조회 시작일 (ISO 8601, e.g. 2026-06-24)",
            },
            "to": {
                "type": "string",
                "description": "조회 종료일 (ISO 8601, e.g. 2026-06-30)",
            },
        },
        "required": ["from", "to"],
    },
}
```

description을 한국어로 쓴 건 Claude 한국어 응답 품질을 위해서다
Round 2에서는 `tools = None`으로 넘겨서 재호출 시 툴 자체를 비활성화한다

### 2단계 — Round 1: tool_use 이벤트 수신

Claude가 툴을 선택하면 `content_block_start`에서 `tool_use` 타입 블록이 시작된다
input은 `input_json_delta`로 조각조각 오다가 `content_block_stop`에서 완성된다

이때 돌아오는 `tool_use_id`가 중요하다
Round 2에서 결과를 돌려줄 때 반드시 이 id를 그대로 써야 Claude가 어느 호출에 대한 결과인지 매칭한다

```python
elif event_type == "content_block_stop":
    if is_tool_block and current_tool_id and current_tool_name:
        parsed_input = json.loads(current_tool_input) if current_tool_input else {}
        yield (
            f"data: {json.dumps({'type': 'tool_use', 'id': current_tool_id, 'name': current_tool_name, 'input': parsed_input})}\n\n"
        )
        is_tool_block = False
        current_tool_id = None
        current_tool_name = None
        current_tool_input = ""
```

NestJS 쪽에서는 이 이벤트를 받으면 스트림을 멈추고 tool_use 정보를 저장해둔다

```typescript
// message.service.ts :: streamMessage()
let toolUseEvent: PendingToolUse | null = null;

for await (const chunk of this.inferenceClient.streamChat(basePayload)) {
    const parsed = JSON.parse(jsonStr);

    if (parsed.type === 'tool_use' && typeof parsed.id === 'string') {
        toolUseEvent = {
            id: parsed.id,
            name: parsed.name,
            input: (parsed.input ?? {}) as Record<string, unknown>,
        };
        break;
    }

    if (typeof textContent === 'string') accumulatedText += textContent;
    yield chunk;
}
```

### 3단계 — 서버에서 함수 실행

`MessageService`가 tool_use 이름을 보고 적절한 서비스 함수를 호출한다
현재는 `get_free_slots`만 지원하고, 캘린더 서비스를 호출한다

```typescript
if (toolUseEvent) {
    const slots = await this.handleGetFreeSlots(user.id, toolUseEvent);
    const top3 = selectTop3Slots(slots);

    const slotEvent = JSON.stringify({ type: 'slot_suggestion', slots: top3 });
    yield `data: ${slotEvent}\n\n`;

    for await (const chunk of this.inferenceClient.streamChat({
        ...basePayload,
        pendingToolUse: toolUseEvent,
        toolResults: [{ toolUseId: toolUseEvent.id, content: JSON.stringify(top3) }],
    })) { ... }
}
```

`slot_suggestion` 이벤트는 Claude가 보내는 게 아니라 NestJS가 슬롯 조회 후 직접 삽입한 커스텀 이벤트다
SSE 스트림 중간에 섞여 있어서 Claude 응답처럼 보이기 쉬운데, 클라이언트(`useChat.ts`)에서 `type === 'slot_suggestion'`으로 따로 분기해서 처리한다

### 4단계 — Round 2: tool_result 주입

`tool_result` 블록으로 함수 실행 결과를 messages에 추가한다
`tool_use_id`를 매칭시켜야 Claude가 어느 툴 호출에 대한 결과인지 알 수 있다

```python
messages = [
    {"role": "user", "content": "언제 시간 돼?"},
    {"role": "assistant", "content": [{"type": "tool_use", "id": "toolu_xxx", "name": "get_free_slots", "input": {...}}]},
    {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "toolu_xxx", "content": "[{...slots...}]"}]},
]
```

JARVIS AI 코드에서는 이 구조를 함수로 만들어서 쓴다

```python
def _build_round2_messages(base_messages, pending_tool_use, tool_results) -> list[dict]:
    messages = list(base_messages)

    tool_use_block = {
        "type": "tool_use",
        "id": pending_tool_use.id,
        "name": pending_tool_use.name,
        "input": pending_tool_use.input,
    }
    messages.append({"role": "assistant", "content": [tool_use_block]})

    tool_result_blocks = [
        {
            "type": "tool_result",
            "tool_use_id": tr.tool_use_id,
            "content": tr.content,
        }
        for tr in tool_results
    ]
    messages.append({"role": "user", "content": tool_result_blocks})

    return messages
```

Round 2에서는 `tools = None if is_round2 else [GET_FREE_SLOTS_TOOL]`로 툴을 꺼둔다

## 삽질한 것

tool_use_id가 일치하지 않으면 Claude가 오류 응답을 낸다
`tool_result`의 `tool_use_id`가 `tool_use`의 `id`와 다르면 Claude가 인식을 못 하기 때문이다
`pending_tool_use.id`를 `tool_results[0].tool_use_id`에 그대로 넘기면 해결된다

Round 2에서 tools를 안 지우면 무한 루프 위험이 있다
tools가 남아있으면 Claude가 Round 2에서도 또 tool_use를 반환할 수 있어서다
`tools = None if is_round2 else [GET_FREE_SLOTS_TOOL]`로 명시적으로 꺼야 한다
