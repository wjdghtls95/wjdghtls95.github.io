---
title: "async generator — 비동기 스트림 다루기"
description: "async generator — 비동기 스트림 다루기"
date: "2026-07-31"
tags: ["learning"]
study: "학습/TypeScript/async-generator.md"
---

# Async Generator & for await...of
_Updated: 2026-06-24_

---

> [!note]- 용어 정리
> - **Generator**: `function*` 문법으로 만든 함수. `yield`로 값을 하나씩 내보내고 일시 중단됨
> - **AsyncGenerator**: `async function*` 문법. yield한 값이 Promise로 감싸짐
> - **AsyncIterable**: `Symbol.asyncIterator`를 구현한 객체 — `for await...of`로 순회 가능
> - **for await...of**: AsyncIterable/AsyncGenerator를 순서대로 소비하는 ES2018 문법

---

## 왜 필요한가

- 일반 `return`은 값을 한 번에 다 돌려줌 — 스트리밍 불가
- `for...of`는 동기 Iterable만 순회 — 비동기 스트림을 처리 못 함
- `for await...of` + `async function*`을 조합하면 **값을 하나씩 생산 → 소비**하는 비동기 파이프라인 구성 가능

---

## 핵심 원리

```
async function* generator() {
  yield '첫 번째'   // 여기서 일시 중단, 첫 번째 값 반환
  yield '두 번째'   // 재개, 두 번째 값 반환
  yield '세 번째'
}

for await (const value of generator()) {
  console.log(value) // '첫 번째' → '두 번째' → '세 번째' 순서 보장
}
```

- `yield`할 때마다 generator가 일시 중단 → caller가 값 처리 → generator 재개
- `for await`는 각 yield를 `await`로 기다림 → 순서 보장

---

## 일반 for...of와 차이

| | `for...of` | `for await...of` |
|---|---|---|
| 대상 | `Iterable<T>` (배열, Set, Map) | `AsyncIterable<T>` / `AsyncGenerator<T>` |
| 값 처리 | 동기 | 각 값마다 `await` |
| 문법 | `for (const x of iter)` | `for await (const x of iter)` |
| 잘못 쓰면 | — | TypeScript 컴파일 에러 |

---

## JARVIS AI 실제 코드

### SSE 스트리밍 소비

`apps/server/src/message/message.service.ts` — `streamMessage()`

```ts
// inferenceClient.streamChat()이 AsyncGenerator<string>을 반환
const round1Stream = this.inferenceClient.streamChat(basePayload);

for await (const rawLine of round1Stream) {
  // rawLine = 'data: {"type":"text_delta","text":"안녕"}\n\n'
  if (rawLine.trim().replace(/^data:\s*/, '') === '[DONE]') {
    completed = true;
    break;
  }
  // ...
  yield rawLine; // 이 함수 자체도 async generator라서 yield 가능
}
```

- `streamMessage()` 자체가 `async *` — Controller가 `for await`로 소비
- `inferenceClient.streamChat()` — inference 서버에서 SSE 청크를 하나씩 yield
- **중첩 generator 파이프라인**: inference → messageService → controller → client

---

## async function* 선언 방법

```ts
// 1. 독립 함수
async function* streamNumbers() {
  for (let i = 0; i < 5; i++) {
    await delay(100);
    yield i;
  }
}

// 2. 클래스 메서드 (NestJS SSE 패턴)
@Injectable()
class MessageService {
  async *streamMessage(...): AsyncGenerator<string> {
    yield 'chunk1';
    yield 'chunk2';
  }
}

// 3. 반환 타입 명시
async function* gen(): AsyncGenerator<number, void, unknown> { ... }
//                                   값 타입   return 타입  next() 인수 타입
```

---

## Gotcha

- **일반 `return`과 혼용 불가**: `return value`는 generator를 종료시킴. `finally` 블록은 여전히 실행됨
  - JARVIS AI: `streamMessage()`의 `finally`가 DB 정리 담당 — generator가 어디서 끝나도 실행됨
- **`for await` 없이 `for...of` 쓰면**: TypeScript가 `AsyncGenerator`는 `Iterable`이 아니라고 에러
- **break하면 generator 종료**: `return()` 메서드가 내부적으로 호출됨 — finally가 실행되고 generator 정리됨
- **에러 처리**: generator 내부에서 throw되면 for await 루프 밖으로 전파됨 → 호출자가 try/catch해야 함

---

## 관련 개념

- TypeScript/generics — `AsyncGenerator<T>`의 T
- NestJS/SSE — Server-Sent Events — NestJS에서 SSE 스트리밍 파이프라인
- Python/Python 비동기 — AsyncIO — Python의 `async for` + `AsyncGenerator` 대응 개념
