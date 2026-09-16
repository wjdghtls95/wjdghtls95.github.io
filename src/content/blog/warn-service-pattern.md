---
title: "WarnService 패턴 — 실패해도 흐름이 계속되어야 하는 작업 처리법"
description: "실패해도 계속 진행돼야 하는 에러를 WarnService의 guard, guardAll로 처리한 이유와 구조"
date: "2026-09-17"
tags: ["NestJS"]
qa_done: true
rewritten: true
---

NestJS에서 치명적 예외는 `AllExceptionFilter`가 잡아준다

`throw new DomainException()`만 던지면 서비스 코드에 try/catch 없이도 로그와 응답 처리가 끝난다

근데 모든 에러가 이렇게 깨끗하게 안 끝난다

실패해도 흐름은 계속 진행돼야 하는 warn 레벨 에러들이 있다

## 왜 필요한가

- JS는 `throw`하면 함수가 그 자리에서 끝난다
  - `return updatedAlert` 같은 후속 코드에 도달 못 한다
  - warn만 남기고 계속 실행하고 싶으면 `throw`를 못 쓴다
- `queue.remove().catch(err => { logger.warn(...) })` 같은 패턴이 서비스 전체에 반복된다
- 서비스마다 `private readonly logger = new Logger(...)` 선언이 중복된다
- `Promise.allSettled` + 실패 필터링 로직이 비즈니스 레이어에 그대로 노출된다

## 어떻게 동작하나

WarnService는 세 가지 메서드로 나뉜다

- `warn()` — 로그만 남긴다
- `guard()` — 단일 비동기 작업을 try/catch로 감싸고, 실패하면 undefined를 반환한다
- `guardAll()` — 여러 비동기 작업을 `Promise.allSettled`로 돌리고, 실패한 것만 모아 한 번에 warn 로그를 남긴다

```typescript
@Injectable()
export class WarnService {
  private readonly logger = new Logger('ServiceLayer');

  warn(warnCode: ServiceWarnCode, data?: unknown): void

  async guard<T>(operation: Promise<T>, code: ServiceWarnCode): Promise<T | undefined> {
    try { return await operation; }
    catch (err: unknown) { this.warn(code, err); return undefined; }
  }

  async guardAll<T>(operations: Promise<T>[], code: ServiceWarnCode): Promise<void> {
    const results = await Promise.allSettled(operations);
    const failed = results.filter(r => r.status === 'rejected');
    if (failed.length > 0) {
      this.warn(code, { failedCount: failed.length, totalCount: results.length, reasons: ... });
    }
  }
}
```

`guard()`는 try/catch를 인프라 코드 안에 숨긴다

caller는 실패 여부를 신경 안 쓰고 undefined를 받은 다음 줄로 그냥 넘어간다

`guardAll()`은 개별 실패마다 로그를 남기지 않는다

`rejected` 상태만 필터링해서 실패 개수, 전체 개수, 이유를 한 번에 묶어 warn 하나로 남긴다

`WarnModule`을 `@Global()`로 선언해두면 CoreModule에서 한 번만 import해도 앱 전체에서 DI로 쓸 수 있다

## JARVIS에서 실제로 어떻게 썼나

`alert.service.ts`에서 `queue.remove(alertId)`를 호출하는 코드가 계기였다

`Queue.remove()`는 active job이면 throw가 아니라 `0`을 반환한다

`Job.remove()`와는 다른 동작이다

이 반환값을 체크하려고 `.then()`으로 0인지 확인하고 `.catch()`로 throw까지 잡는 체이닝이 붙어 있었다

`cancelAllForEvent`에서도 `Promise.allSettled` + `failures.filter` + `logger.error` 패턴이 똑같이 반복됐다

WarnService를 붙인 뒤 `alert.service.ts`에서 `.catch()` 3개, `.then()` 1개, `this.logger` 선언, `cancelPendingAlert` wrapper가 전부 사라졌다

## 삽질한 것 / 함정

- `Queue.remove()`가 active job에서 throw할 거라고 예상했는데, 실제로는 `0`을 반환했다
  - `Job.remove()`와 헷갈리기 쉬운 부분
- `await new ServiceWarn(code)` 형태로 PromiseLike를 직접 구현하려던 시도는 기각했다
  - 전역 뮤터블 싱글톤이 필요했고, `await`를 빼먹어도 타입 에러가 안 나는 문제가 있었다
- `this.eventEmitter.emit(SERVICE_LOG_EVENT, ...)`로 이벤트 기반 로깅도 검토했다
  - 비동기 이벤트라 처리 보장이 없고, WarnService를 직접 주입하는 것보다 복잡해서 접었다
