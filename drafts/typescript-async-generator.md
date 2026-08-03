---
title: "async generator — 비동기 스트림 다루기"
description: "yield로 값을 하나씩 내보내는 async generator와 for await...of의 동작 원리, 그리고 SSE 스트리밍에서 실제로 쓰이는 방식"
date: "2026-07-31"
tags: ["TypeScript"]
study: "학습/TypeScript/async-generator.md"
rewritten: true
---

AI 채팅 응답을 스트리밍으로 받아본 적 있다면, 그 뒤에는 async generator가 있다.

Claude API든 OpenAI든 스트리밍 응답은 전부 SSE(Server-Sent Events) 청크를 하나씩 보내는 방식이다. 서버에서 이 청크들을 받아서 클라이언트로 다시 흘려보낼 때 `async function*`이 핵심 도구가 된다.

## 왜 필요한가

일반 `return`은 한 번에 값을 다 돌려준다. 스트리밍이 안 된다.

`for...of`는 동기 Iterable만 순회한다. `Promise`가 섞인 비동기 스트림을 처리하면 타입 에러가 난다.

`async function*` + `for await...of`를 조합하면 **값을 하나씩 생산 → 소비**하는 비동기 파이프라인을 만들 수 있다. 각 `yield`마다 일시 중단되고, 소비자가 처리를 마치면 재개된다.

## 핵심 동작

```ts
async function* generator() {
  yield '첫 번째'   // 여기서 일시 중단, 첫 번째 값 반환
  yield '두 번째'   // 재개, 두 번째 값 반환
  yield '세 번째'
}

for await (const value of generator()) {
  console.log(value) // '첫 번째' → '두 번째' → '세 번째' 순서 보장
}
```

`yield`마다 generator가 멈추고, `for await`가 값을 받아 처리한 뒤 다음 `yield`로 넘어간다. 순서가 보장된다.

## for...of와 for await...of 차이

| | `for...of` | `for await...of` |
|---|---|---|
| 대상 | `Iterable<T>` (배열, Set, Map) | `AsyncIterable<T>` / `AsyncGenerator<T>` |
| 값 처리 | 동기 | 각 값마다 `await` |
| 잘못 쓰면 | — | TypeScript 컴파일 에러 |

`AsyncGenerator`에 `for...of`를 쓰면 TypeScript가 "이건 Iterable이 아니야"라고 에러를 낸다.

## 선언 방법

```ts
// ✅ 독립 함수
async function* streamNumbers() {
  for (let i = 0; i < 5; i++) {
    await delay(100);
    yield i;
  }
}

// ✅ 클래스 메서드 (NestJS 패턴)
@Injectable()
class MessageService {
  async *streamMessage(...): AsyncGenerator<string> {
    yield 'chunk1';
    yield 'chunk2';
  }
}

// ✅ 반환 타입 명시
async function* gen(): AsyncGenerator<number, void, unknown> { ... }
//                                   값 타입   return 타입  next() 인수 타입
```

## JARVIS에서 실제로 쓰는 방식

JARVIS AI 서버(`apps/server/src/message/message.service.ts`)의 `streamMessage()`는 그 자체가 async generator다.

```ts
const round1Stream = this.inferenceClient.streamChat(basePayload);

for await (const rawLine of round1Stream) {
  if (rawLine.trim().replace(/^data:\s*/, '') === '[DONE]') {
    completed = true;
    break;
  }
  yield rawLine; // 이 함수도 async generator라서 yield 가능
}
```

`inferenceClient.streamChat()`이 Claude API SSE 청크를 하나씩 yield하고, `streamMessage()`가 그걸 받아서 다시 yield한다. Controller가 그걸 받아서 클라이언트로 보낸다.

**중첩 파이프라인**: inference 서버 → `inferenceClient` → `messageService` → Controller → 브라우저

각 레이어가 async generator를 받아서 처리하고 다시 yield하는 구조다. 실제로 이렇게 쓰고 나면 "왜 async generator가 필요한가"가 바로 이해된다.

## 주의할 점

**`return value`는 generator를 종료**시킨다. `yield value`가 아니면 스트리밍이 그 시점에 끝난다.

**`finally`는 항상 실행**된다. `break`로 루프를 탈출하거나, 예외가 던져지거나, generator가 끝까지 소비되거나 — 어떤 경우든 `finally`가 실행된다. JARVIS의 `streamMessage()`에서 `finally`가 DB 저장과 대화 제목 생성을 담당하는 이유다. generator가 어디서 끊겨도 정리가 된다.

**에러 처리**: generator 내부에서 throw가 나면 `for await` 루프 밖으로 전파된다. 호출자가 `try/catch`로 잡아야 한다.

```ts
// ✅ 에러가 for await 밖으로 전파됨
try {
  for await (const chunk of streamMessage()) {
    // ...
  }
} catch (e) {
  // generator 내부 에러가 여기로 옴
}
```

에러 처리 예시가 catch 래퍼만 보여주고 generator 내부에서 실제로 throw하는 코드가 없고 어디서 에러가 오는지 불명확
```ts
async function* riskyGen() {
  yield 1;
  throw new Error('서버 에러');
  yield 2; // 실행 안 됨
}

try {
  for await (const v of riskyGen()) {
    console.log(v); // 1 출력
  }
} catch (e) {
  console.error(e.message); // '서버 에러'
}
```