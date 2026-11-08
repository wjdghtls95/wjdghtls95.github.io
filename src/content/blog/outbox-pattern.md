---
title: "Outbox Pattern — 메시지 유실 없이 이벤트를 발행하는 법"
description: "DB와 큐에 동시에 쓸 때 생기는 고아 데이터를 outbox 테이블로 막는 원리와, JARVIS가 도입 대신 선택한 방법"
date: "2026-11-08"
tags: ["아키텍처"]
qa_done: true
rewritten: true
---

DB에 저장하고 나서 큐에 작업을 넣는 코드는 어디에나 있다

```ts
// ❌ 두 시스템에 따로 쓴다
const alert = await this.alertRepository.create(dto) // PostgreSQL
await this.queue.add('send-alert', { alertId: alert.id }) // Redis(BullMQ)
```

`queue.add()`가 실패하면 DB에는 PENDING 상태의 행이 남는다
그 행을 처리할 잡은 영원히 만들어지지 않는다
알림은 영구 미발송이고 아무도 모른다

JARVIS의 `createAlertSlot()`을 분석하다 발견한 문제가 정확히 이 모양이었다

## 왜 try-catch로는 안 되나

PostgreSQL과 Redis는 각자 독립적인 트랜잭션 매니저를 가진다
하나의 트랜잭션으로 둘을 묶어서 원자적으로 커밋할 방법이 없다 (분산 트랜잭션이 어려운 이유)

그럼 `queue.add()` 실패 시 DB 행을 지우는 보상 트랜잭션을 두면 어떨까
보상 로직 자체도 실패할 수 있다
실패를 처리하는 코드가 또 실패하면 같은 문제가 한 겹 더 생길 뿐이다

## Outbox: 외부에 쓰지 말고 DB에 적어둔다

핵심은 외부 시스템에 대한 write를 "나중에 할 일"로 바꿔서 DB 안에 기록하는 것이다

```ts
// ✅ 원본 데이터와 outbox 행을 같은 트랜잭션으로 저장
await prisma.$transaction(async (tx) => {
  const alert = await tx.alert.create({ data: dto })
  await tx.outbox.create({
    data: { type: 'send-alert', payload: { alertId: alert.id } },
  })
})
```

둘 다 PostgreSQL 안에서 일어나니까 DB 트랜잭션의 원자성을 그대로 쓴다
알림 행이 있으면 outbox 행도 있고, 롤백되면 둘 다 없다

실제 전달은 별도의 polling worker가 맡는다

1. outbox 테이블을 읽는다
2. BullMQ나 FCM 같은 외부 시스템에 전달한다
3. 성공하면 outbox 행을 삭제한다
4. 실패하면 행이 남아 있으니 다음 주기에 재시도한다

이름이 Outbox인 이유가 여기 있다
이메일을 바로 보내지 않고 발신함에 쌓아두면, 전송은 별도 프로세스가 책임진다

## 공짜는 아니다

### at-least-once라서 중복이 생긴다

worker가 외부 시스템에 전달은 성공했는데 outbox 행을 지우기 전에 죽으면 다음 주기에 같은 메시지를 또 보낸다
그래서 수신 측이 멱등해야 한다
같은 `alertId`로 FCM을 두 번 보내도 사용자에게 알림이 두 번 가지 않게 만들어야 한다

### 순서는 직접 챙겨야 한다

outbox 행에 `created_at`이나 `sequence` 컬럼을 두고 그 순서대로 처리하면 순서를 보장할 수 있다

### 운영해야 할 게 하나 늘어난다

polling worker라는 새 프로세스가 생긴다
주기가 짧으면 DB 부하가 늘고 길면 전달이 늦어진다
이 균형점을 잡는 실제 기준은 아직 모른다

## JARVIS는 Outbox를 쓰지 않았다

지금은 outbox 테이블을 만들지 않고 `@Transactional()`과 예외 전파를 선택했다

- `queue.add()`가 예외를 던지면 `@Transactional()` 데코레이터가 Prisma 트랜잭션을 롤백한다
- 추가 인프라 없이 BullMQ 케이스는 해결된다

이유는 비용이다
polling worker를 운영하는 비용이 MVP 단계에서 요구되는 정합성 수준보다 크다고 판단했다

### 남은 구멍

이 방식은 BullMQ까지만 커버한다
`cacheService.del/set` 같은 Redis write는 Prisma의 CLS 컨텍스트에 참여하지 않아서 같은 패턴이 안 통한다
DB는 롤백됐는데 캐시는 이미 바뀐 상태가 될 수 있다

진짜 Outbox가 필요해지는 시점은 이 케이스가 실제로 문제를 일으킬 때다

## Outbox가 더 나은 상황

- 큐 말고도 외부 API나 여러 시스템으로 이벤트를 내보내야 할 때
- 메시지 유실이 곧 금전적 손실이나 데이터 불일치로 이어질 때
- 예외 전파만으로 커버되지 않는 write가 계속 늘어날 때

반대로 대상이 BullMQ 하나뿐이고 실패 시 요청 전체를 롤백해도 괜찮다면 `@Transactional()`과 예외 전파가 훨씬 가볍다

## 참고

- Chris Richardson, *Microservices Patterns* (2018) 의 Transactional Outbox 챕터
- Hohpe & Woolf, *Enterprise Integration Patterns* (2003) 의 Message Store, Guaranteed Delivery
