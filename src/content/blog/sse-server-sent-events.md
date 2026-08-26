---
title: "NestJS SSE — 서버에서 클라이언트로 실시간 스트림 보내기"
description: "AI 응답을 실시간으로 흘려보내야 할 때 NestJS 공식 SSE 대신 AsyncGenerator를 고른 이유"
date: "2026-08-27"
tags: ["NestJS"]
qa_done: true
rewritten: true
phase: "chat"
---

AI 응답은 완성까지 수 초에서 수십 초가 걸린다

전체 응답이 끝날 때까지 기다리게 하면 그동안 화면은 그대로다

이걸 풀려고 쓰는 게 SSE (Server-Sent Events)

서버에서 클라이언트로 한 방향으로 흐르는 실시간 스트림 프로토콜이고, WebSocket과 달리 일반 HTTP 위에서 그대로 동작한다

## 왜 공식 방식을 안 썼나

NestJS 공식 문서는 `@Sse()` 데코레이터와 `Observable<MessageEvent>` 조합을 소개한다

```typescript
❌ 공식 예제 — @Sse() + Observable
@Sse('sse')
sse(): Observable<MessageEvent> {
  return interval(1000).pipe(map(() => ({ data: { hello: 'world' } })));
}
```

이 방식은 RxJS 의존성이 생기고, 스트림 중단이나 에러 처리를 세밀하게 제어하기 어려워진다

JARVIS AI에서는 `@Res()` + `for await...of` AsyncGenerator로 HTTP keep-alive 연결을 직접 관리하는 쪽을 택했다

```typescript
✅ JARVIS AI 실제 코드 — message.controller.ts
@Post()
async handleSendMessage(
  @CurrentUser() user: User,
  @Param('conversationId') conversationId: string,
  @Body() dto: SendMessageDto,
  @Res() res: Response,
) {
  // ownership check BEFORE headers committed — AllExceptionFilter가 403/404 반환 가능
  await this.conversationService.getConversationOrThrow(user.id, conversationId);

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');
  res.flushHeaders();  // 헤더 즉시 전송 — 브라우저가 스트림 수신 시작

  try {
    for await (const chunk of this.messageService.streamMessage(user, conversationId, dto)) {
      res.write(chunk);
    }
    res.write('data: [DONE]\n\n');
  } catch {
    res.write(`data: ${JSON.stringify({ error: 'stream_failed' })}\n\n`);
  } finally {
    res.end();
  }
}
```

차이는 타이밍에 있다

공식 방식은 NestJS가 헤더를 자동으로 설정해서 직접 에러 처리가 안 된다

JARVIS AI 방식은 `flushHeaders()` 호출 전에 소유권 검증을 끝내서, 403이나 404를 일반 JSON 에러로 그대로 반환할 수 있다

헤더가 한 번 전송되면 그 이후로는 HTTP 상태 코드를 바꿀 수 없다

예외는 반드시 그 전에 던져야 한다

## 스트림이 흐르는 순서

- 브라우저가 `POST /conversations/:id/messages` 요청
- NestJS가 `Content-Type: text/event-stream` 헤더 설정하고 `flushHeaders()`
- NestJS가 FastAPI 추론 서버에 `/chat/stream`으로 요청, 연결 유지
- 텍스트 청크가 올 때마다 추론 서버 → NestJS → 브라우저로 그대로 릴레이
- 중간에 `tool_use` 이벤트가 오면 NestJS가 캘린더 API 같은 실제 동작을 실행하고, 결과를 다시 추론 서버에 보내 2차 스트림을 이어받음
- 추론 서버가 `[DONE]`을 보내면 NestJS도 `[DONE]`을 한 번 더 쓰고 `res.end()`로 연결 종료

## AsyncGenerator로 스트림 만들기

Observable 방식은 옵저버 패턴으로 `next()` / `complete()`를 호출하는 구조다

AsyncGenerator는 그냥 `yield`로 값을 흘려보내는 구조라 흐름이 더 직선적이다

```typescript
✅ JARVIS AI 실제 코드 — message.service.ts
async *streamMessage(
  user: User,
  conversationId: string,
  dto: SendMessageDto,
): AsyncGenerator<string> {
  // ...
  for await (const chunk of this.inferenceClient.streamChat(basePayload)) {
    if (chunk.trim().replace(/^data:\s*/, '') === '[DONE]') {
      completed = true;
      break;
    }
    // tool_use 이벤트 감지 → Round 2 처리
    const parsed = JSON.parse(jsonStr);
    if (parsed.type === 'tool_use') {
      toolUseEvent = { id: parsed.id, name: parsed.name, input: parsed.input };
      break;
    }
    yield chunk;  // 브라우저에 즉시 전송
  }
}
```

FastAPI 쪽 원본 스트림은 `ReadableStream`으로 온다

이걸 파싱하는 코드가 `inference.client.ts`

```typescript
✅ JARVIS AI 실제 코드 — inference.client.ts
async *streamChat(payload: ChatStreamPayload): AsyncGenerator<string> {
  const response = await fetch(`${inferenceUrl}/chat/stream`, { ... });
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split('\n\n');  // 이중 개행으로 이벤트 분리
    buffer = frames.pop() ?? '';          // 마지막 미완성 프레임 버퍼에 유지

    for (const frame of frames) {
      if (!frame.trim()) continue;
      yield `${frame}\n\n`;
    }
  }
}
```

SSE 이벤트는 `data: ...\n\n` 형식으로, 페이로드 뒤에 이중 개행을 붙여 이벤트를 구분한다

`buffer.split('\n\n')`으로 프레임을 나누고, `frames.pop()`으로 마지막 미완성 프레임은 버퍼에 남겨둔다

## 삽질한 것

- `res.flushHeaders()` 전에 예외를 던져야 에러 응답이 가능하다, 헤더가 커밋된 후에는 상태 코드를 바꿀 수 없다
- `@Res()`를 쓰면 `passthrough` 기본값이 `false`라 NestJS interceptor가 응답을 가로채지 않는다, `@Res({ passthrough: true })`로 바꾸면 이 흐름과 충돌
- `TextDecoder`에 `stream: true` 옵션이 빠지면 한글 같은 멀티바이트 문자가 청크 경계에서 깨진다
- `frames.pop()`으로 버퍼를 관리하지 않으면 같은 이벤트가 두 번 yield된다
- 추론 서버가 이미 `[DONE]`을 보내도, NestJS가 별도로 `[DONE]`을 한 번 더 써야 클라이언트가 스트림 종료를 인식한다
