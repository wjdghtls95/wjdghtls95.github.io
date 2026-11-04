---
title: "Redis Rate Limiting 원자성, INCR+EXPIRE의 함정과 SET NX 해결법"
description: "일일 채팅 한도 카운터가 TTL 없이 영구 잔존하는 버그를 SET NX + INCR 조합으로 막은 과정"
date: "2026-11-04"
tags: ["아키텍처"]
qa_done: true
rewritten: true
---

일일 사용량 제한은 Redis 카운터로 구현하는 게 가장 흔한 방법이다
JARVIS도 FREE 플랜 채팅에 하루 20회 한도를 걸었고, 서버는 Redis 카운터로 관리하고 웹은 429 응답을 감지해서 배너를 띄우고 입력창을 막는다

가장 단순하게 짜면 이렇게 나온다
그런데 이 코드에는 원자성 문제가 숨어 있다

```ts
// ❌ 원자성 없음
await redis.incr(key);        // 카운터 증가
await redis.expire(key, ttl); // TTL 설정
```

## INCR + EXPIRE가 위험한 이유

두 명령은 서로 다른 요청이라 사이에 틈이 있다
`incr`는 성공했는데 `expire` 전에 프로세스가 종료되면 키는 TTL 없이 그대로 남는다

TTL이 없으면 자정이 지나도 카운터가 초기화되지 않는다
그 유저는 한도를 넘긴 채로 영구 차단된다

평소엔 절대 안 터지다가 배포나 재시작 타이밍에만 걸리는 유형이라 눈에 잘 안 띄는 게 더 문제다

## 해결: SET NX EX 먼저, 그다음 INCR

```ts
// ✅ SET NX: 키 없을 때만 TTL과 함께 0으로 초기화 (원자적)
await redis.set(key, 0, 'EX', ttlSeconds, 'NX');
// INCR: TTL 유지한 채로 숫자만 증가
const count = await redis.incr(key);

if (count > DAILY_FREE_LIMIT) {
  throw new DomainException(DOMAIN_ERRORS.CHAT_RATE_LIMIT_EXCEEDED);
}
```

순서가 핵심이다

- `SET NX EX`가 먼저 실행된다, 키가 없을 때만 값 0과 TTL을 한 번에 세팅하고 이미 있으면 아무것도 안 한다
- `INCR`는 키가 있든 없든 +1만 하고 기존 TTL은 건드리지 않는다

두 명령 사이에 프로세스가 죽어도 괜찮다
TTL은 키가 만들어지는 순간 같은 명령 안에서 이미 붙어 있으니 TTL 없는 키가 생길 수 없다

## 자정까지 남은 초로 TTL 계산

카운터는 "하루"가 지나면 초기화돼야 하니 TTL은 유저 현지 자정까지 남은 초로 잡는다

```ts
function secondsUntilLocalMidnight(timezoneOffsetMinutes: number): number {
  const now = new Date();
  const localMidnight = new Date(now);
  localMidnight.setMinutes(localMidnight.getMinutes() + timezoneOffsetMinutes);
  localMidnight.setHours(24, 0, 0, 0);
  localMidnight.setMinutes(localMidnight.getMinutes() - timezoneOffsetMinutes);
  return Math.ceil((localMidnight.getTime() - now.getTime()) / 1000);
}
```

UTC 자정이 아니라 유저 시간대 기준이라 한국 유저는 한국 자정에 카운터가 리셋된다

## Redis가 죽으면 어떻게 할까

Rate limiting은 보호 장치지 핵심 기능이 아니다
Redis 장애 때문에 채팅 자체가 막히는 건 손해가 더 크다고 판단해서, 실패하면 경고만 남기고 통과시킨다

```ts
const count = await this.chatRateLimitService
  .checkAndIncrement(userId, timezoneOffset)
  .catch(() => {
    this.warnService.guard(/* CHAT_RATE_LIMIT_CACHE_FAILED */);
    return 0; // 장애 시 통과
  });
```

엄격한 차단보다 가용성을 우선한 선택이다
장애 동안은 한도가 느슨해지는 대가를 받아들이는 구조다

## TDD로 먼저 잡은 케이스

이 원자성 문제는 구현 후 리뷰가 아니라 테스트 단계에서 먼저 잡았다

1. Test List에 "TTL 없이 키가 영구 잔존하는 경계 조건"을 추가
2. `incr + expire` 방식으로 테스트를 작성해서 Red 확인
3. 구현을 SET NX + INCR로 변경
4. Green

코드리뷰에서 따로 지적받지 않았던 부분이라, 경계 조건을 테스트 목록에 먼저 적어두는 습관이 효과가 있었던 케이스다

## 카운터와 TTL 사이의 틈

카운터 + TTL 조합은 "값을 바꾸는 명령"과 "수명을 정하는 명령"이 분리되는 순간 틈이 생긴다
키를 만드는 시점에 TTL까지 한 번에 붙이고, 이후엔 TTL에 손대지 않는 명령만 쓰면 된다
