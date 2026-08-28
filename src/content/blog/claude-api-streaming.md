---
title: "Claude API 스트리밍 — SDK 이벤트 구조부터 브라우저 파싱까지"
description: "공식 문서가 설명 안 하는 SSE 이벤트 타입과, FastAPI·브라우저에서 각각 다르게 처리하는 이유"
date: "2026-08-29"
tags: ["AI"]
qa_done: true
rewritten: true
phase: "chat"
---

Claude 같은 LLM은 응답 생성에 수 초에서 수십 초가 걸린다

전체 응답이 끝날 때까지 기다리게 하면 그동안 화면은 멈춰있다

Claude API는 이 문제를 스트리밍으로 푼다

토큰이 생성되는 즉시 이벤트로 흘려보낸다

공식 문서는 "응답이 SSE(Server-Sent Events)로 온다"까지만 알려준다

SSE 안에 이벤트 타입이 몇 종류인지, 그걸 받아서 어떻게 처리하는지는 나와 있지 않다

## SDK가 보내는 이벤트 구조

Claude SDK를 스트리밍 모드로 호출하면, 응답은 하나의 텍스트 덩어리가 아니라 여러 이벤트로 쪼개져서 온다

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","usage":{"input_tokens":10,...}}}

event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"안녕"}}

event: content_block_stop
data: {"type":"content_block_stop","index":0}

event: message_delta
data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":20}}
```

이벤트는 크게 세 층으로 나뉜다

- `message_start` / `message_delta`: 메시지 메타데이터, 토큰 사용량 포함
- `content_block_start` / `content_block_stop`: 블록 하나의 시작과 끝
- `content_block_delta`: 블록 내용의 증분, 텍스트는 `text_delta`, Tool Use는 `input_json_delta`

텍스트와 Tool Use가 같은 이벤트 흐름을 타지만, delta 타입만 다르다는 게 핵심이다

## FastAPI에서 이벤트를 다시 포장하는 이유

SDK가 주는 이벤트를 그대로 흘려보내도 되지만, JARVIS는 FastAPI 레이어에서 한 번 더 손을 댄다

내부적으로는 `text_delta`와 `tool_use` 두 종류로만 단순화해서 다시 yield한다

```python
async with claude.messages.stream(**kwargs) as stream:
    async for event in stream:
        event_type = event.type

        if event_type == "content_block_start":
            block = event.content_block
            if block.type == "tool_use":
                is_tool_block = True
                current_tool_id = block.id
                current_tool_name = block.name
            else:
                is_tool_block = False

        elif event_type == "content_block_delta":
            delta = event.delta
            if is_tool_block and delta.type == "input_json_delta":
                current_tool_input += delta.partial_json
            elif not is_tool_block and delta.type == "text_delta":
                yield f"data: {json.dumps({'type': 'text_delta', 'text': delta.text})}\n\n"

        elif event_type == "content_block_stop":
            if is_tool_block and current_tool_id:
                parsed_input = json.loads(current_tool_input) if current_tool_input else {}
                yield f"data: {json.dumps({'type': 'tool_use', 'id': current_tool_id, 'name': current_tool_name, 'input': parsed_input})}\n\n"
```

Tool Use의 input은 `input_json_delta`로 조각조각 나눠서 온다

조각난 상태에서는 완전한 JSON이 아니라서 파싱이 안 된다

그래서 `content_block_delta` 단계에서는 문자열로 이어붙이기만 하고, 블록이 끝났다는 신호인 `content_block_stop`에서 한 번에 파싱한다

중간에 파싱을 시도하면 매번 에러가 난다

## NestJS를 지나 브라우저까지

여기서부터는 NestJS가 이 SSE 프레임을 그대로 릴레이해서 브라우저에 전달하는데, 그 부분은 이전 글에서 다뤘다

마지막 구간, 브라우저가 스트림을 받는 방법만 짚는다

브라우저 표준은 `EventSource`다

```javascript
❌ 브라우저 표준 — EventSource
const evtSource = new EventSource('/sse')
evtSource.onmessage = (event) => { console.log(event.data) }
```

JARVIS는 이걸 안 쓰고 `fetch` + `ReadableStream` 조합을 쓴다

- `EventSource`는 GET 요청만 가능, 메시지 전송은 POST라 애초에 안 맞음
- `EventSource`는 커스텀 헤더를 못 붙임, JWT를 `Authorization` 헤더로 보내야 하는데 방법이 없음

```typescript
✅ JARVIS 실제 방식 — fetch + ReadableStream
const res = await fetch(`${API_URL}/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getAccessToken() ?? ''}`,
    },
    body: JSON.stringify({ content }),
})

const reader = res.body.getReader()
const decoder = new TextDecoder()

while (!isDone) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    const result = processLines(lines, accumulated, setStreamingContent, (slots) =>
        setSlotSuggestion({ slots }),
    )
    accumulated = result.accumulated
    isDone = result.isDone
}
```

`EventSource`가 편한 이유는 재연결이나 파싱을 브라우저가 대신 해주기 때문인데, POST와 커스텀 헤더가 막히는 순간 그 편리함은 의미가 없어진다

## Gotcha

- Tool Use의 `input_json_delta`는 완성된 JSON이 아니다, `content_block_stop` 전까지는 문자열로만 누적하고 파싱을 미뤄야 한다
- `text_delta`와 `input_json_delta`는 같은 `content_block_delta` 이벤트 타입 안에 있다, `is_tool_block` 플래그로 분기하지 않으면 텍스트와 Tool 입력이 섞인다
- `EventSource`는 GET + 헤더 제한 때문에 인증이 필요한 스트리밍 API에는 애초에 못 쓴다, `fetch` + `ReadableStream`으로 직접 파싱해야 한다

Claude SDK가 주는 원본 이벤트, FastAPI가 변환한 내부 포맷, 브라우저가 파싱하는 최종 포맷

스트리밍은 이 세 겹을 각 레이어가 자기 사정에 맞게 한 번씩 다시 정리하는 과정이다
