---
title: "CLS와 트랜잭션 전파 — NestJS에서 트랜잭션이 서비스 레이어를 어떻게 넘어가는가"
description: "tx 파라미터 전달을 없애고 @Transactional()로 전파하면서, 인터셉터 방식을 기각한 이유와 BullMQ 경계 설계까지"
date: "2026-11-07"
tags: ["아키텍처"]
qa_done: true
rewritten: true
---

여러 Repository를 한 트랜잭션으로 묶으려면 같은 tx 클라이언트를 모두가 공유해야 한다

가장 쉬운 방법은 `tx`를 파라미터로 계속 넘기는 것이다

```ts
// ❌ tx가 모든 계층의 시그니처를 오염시킨다
async createConversation(dto: CreateDto, tx: Prisma.TransactionClient) {
  const conv = await this.convRepo.create(dto, tx)
  await this.messageRepo.create(conv.id, tx)
  await this.memoryRepo.create(conv.id, tx)
}
```

conversation, message, memory를 동시에 만드는 정도만 돼도 tx가 서비스와 Repository 전 계층을 관통한다

도메인이 늘수록 함수 시그니처가 점점 지저분해진다

## CLS가 해결하는 것

`@nestjs-cls/transactional`은 이 문제를 CLS(Continuation Local Storage)로 푼다

CLS는 async 함수가 다른 async 함수를 호출할 때 스레드 로컬 변수처럼 같은 저장소를 이어받게 해주는 메커니즘이다 (Node.js의 `AsyncLocalStorage` 기반)

`@Transactional()`이 트랜잭션 클라이언트를 CLS에 넣어두면, 호출 체인 어디서든 `txHost.tx`로 꺼낼 수 있다

```ts
// ✅ 시그니처에 tx가 없다
@Transactional()
async createConversation(dto: CreateDto) {
  const conv = await this.convRepo.create(dto)
  await this.messageRepo.create(conv.id)
  await this.memoryRepo.create(conv.id)
}
```

Repository 쪽은 getter 하나만 알면 된다

```ts
export abstract class BaseRepository {
  constructor(protected readonly txHost: PrismaTransactionHost) {}

  protected get db() {
    return this.txHost.tx
    // @Transactional() 안이면 Prisma tx client
    // 밖이면 일반 PrismaClient
  }
}
```

Repository는 자기가 트랜잭션 안에 있는지 몰라도 된다

메서드가 정상 종료되면 COMMIT, 예외가 던져지면 ROLLBACK이다

직접 `AsyncLocalStorage`를 구현할 수도 있지만 Prisma 버전 대응을 직접 해야 해서, 공식 어댑터(`@nestjs-cls/transactional-adapter-prisma`)를 쓰는 쪽이 낫다고 판단했다

## 데코레이터 구현

`@Transactional()`은 메서드를 `withTransaction()`으로 감싸는 데코레이터다

```ts
let _txHost: PrismaTransactionHost | null = null

export function initTransactionHost(txHost: PrismaTransactionHost): void {
  _txHost = txHost
}

export function Transactional(): MethodDecorator {
  return (_target, _key, descriptor: PropertyDescriptor) => {
    const original = descriptor.value as (...args: unknown[]) => Promise<unknown>
    descriptor.value = async function (...args: unknown[]) {
      if (!_txHost) throw new Error('TransactionModule not initialized')
      return _txHost.withTransaction(async () => original.apply(this, args))
    }
    return descriptor
  }
}
```

데코레이터는 DI 컨테이너 밖에서 실행되기 때문에, 모듈 레벨 변수에 `txHost`를 저장해두고 `TransactionModule` 생성자에서 `initTransactionHost()`로 채워 넣는다

## HTTP 인터셉터 방식을 기각한 이유

글로벌 인터셉터에서 `lastValueFrom(next.handle())`를 `withTransaction()`으로 감싸면, 모든 요청을 자동으로 트랜잭션에 넣을 수 있을 것처럼 보인다

이 방식은 두 가지 이유로 기각했다

### 이유 1: Prisma는 callback 모델이다

| 항목 | TypeORM QueryRunner | Prisma `$transaction()` |
|------|--------------------|-----------------------|
| begin/commit | 분리 가능 | callback 모델이라 분리 불가 |
| 인터셉터 통합 | QueryRunner를 CLS에 저장하고 인터셉터에서 commit | 모든 로직이 callback 안에 있어야 함 |
| SSE | 분리 가능해서 호환됨 | SSE 전체가 callback 안에 들어가야 함 |

TypeORM은 begin과 commit을 따로 호출할 수 있어서 인터셉터가 앞뒤를 감쌀 수 있다

Prisma는 `$transaction(async () => { ... })` 안에 로직이 전부 들어가야 같은 tx를 공유한다

begin과 commit을 바깥에서 분리하는 게 구조적으로 안 된다

### 이유 2: SSE가 DB 연결을 붙잡는다

트랜잭션이 시작되면 커넥션 풀에서 연결 하나를 꺼내 COMMIT이나 ROLLBACK까지 독점한다

`lastValueFrom(next.handle())`은 SSE 스트림이 끝날 때까지 기다리므로, LLM 응답을 기다리는 5~30초 내내 연결 하나가 idle 상태로 잡혀 있게 된다

Little's Law로 어림해보면 문제가 선명하다

```
L = λ × W   (평균 연결 수 = 처리율 × 평균 체류 시간)

가정: RPS 50, SSE 비율 30%, SSE 평균 15초, 일반 API 200ms
  L_sse    = 50 × 0.3 × 15  = 225 연결
  L_normal = 50 × 0.7 × 0.2 = 7 연결
```

실측이 아니라 가정한 수치지만, 요청 수는 SSE가 더 적은데도 연결은 SSE가 압도적으로 많이 점유한다는 구조는 변하지 않는다

풀 크기(기본값은 `CPU 코어 수 × 2 + 1`)를 넘기면 일반 API 요청이 연결을 못 받고 타임아웃으로 이어진다

그래서 `@Transactional()`은 필요한 메서드에만 선언하는 Decorator-first로 갔다

SSE 엔드포인트에는 붙이지 않으니 연결 고갈이 생기지 않는다

## BullMQ에서는 범위를 직접 지정한다

BullMQ worker는 HTTP 요청이 아니라서 ClsMiddleware가 실행되지 않는다

그래도 `@Transactional()`은 동작하는데, 내부에서 `cls.run()`을 스스로 호출해 컨텍스트를 만들기 때문이다

문제는 범위다

processor 메서드 전체에 `@Transactional()`을 붙이면 외부 API 호출 같은 네트워크 대기까지 트랜잭션 안에 들어간다

SSE와 같은 이유로 DB 연결을 낭비하게 된다

```ts
@Injectable()
export class TransactionRunner {
  async run<T>(fn: () => Promise<T>): Promise<T> {
    return this.txHost.withTransaction(fn)
  }
}
```

DB 작업 구간만 `TransactionRunner.run()`으로 감싸고, inference API 호출은 바깥에 둔다

```ts
// ❌ 외부 호출이 tx 안에 들어가 연결을 오래 잡는다
@Transactional()
async process(job) {
  const result = await this.inferenceApi.extract(job.data)
  await this.memoryRepo.save(result)
}

// ✅ DB 작업만 tx로 묶는다
async process(job) {
  const result = await this.inferenceApi.extract(job.data)
  await this.txRunner.run(() => this.memoryRepo.save(result))
}
```

## TOCTOU는 delete-first로 줄인다

Refresh Token Rotation처럼 확인하고 사용하는 구간에는 TOCTOU(Time-of-check to time-of-use) 문제가 있다

```ts
// ❌ findUnique(확인) 후 delete(사용), 두 요청이 동시에 확인을 통과할 수 있다
const stored = await txHost.tx.refreshToken.findUnique({ where: { token } })
await txHost.tx.refreshToken.delete({ where: { token } }) // 두 번째 요청은 P2025

// ✅ delete 한 번으로 끝낸다, DB 원자 연산이라 정확히 하나만 성공한다
try {
  stored = await txHost.tx.refreshToken.delete({ where: { token } })
} catch (e) {
  if (e.code === 'P2025') throw new DomainException(DOMAIN_ERRORS.AUTH_INVALID_REFRESH_TOKEN)
  throw e
}
```

확인 단계를 없애고 삭제 자체를 확인으로 쓰는 방식이다

## 세션 무효화는 트랜잭션 바깥에서

토큰 재사용이 감지되면 해당 유저의 모든 세션을 무효화해야 한다

이 작업을 tx 안에서 하면 뒤이어 던지는 예외 때문에 ROLLBACK에 말려들어 DB에 반영되지 않는다

```ts
async rotateRefreshToken(oldToken: string) {
  try {
    return await this.rotate(oldToken) // @Transactional() 메서드
  } catch (e) {
    // tx가 완전히 끝난 뒤에 실행된다
    await this.invalidateAllSessions(userId)
    throw e
  }
}
```

`@Transactional()`은 `private rotate()`에만 붙이고, public 메서드는 tx 바깥에서 catch하는 구조다

## 한계와 아직 모르는 것

`@Transactional()` 안의 DB 쓰기와 `queue.add()`는 여전히 원자적이지 않다

DB 커밋은 됐는데 큐 등록이 실패하면 고아 행이 남을 수 있고, 완전한 해결은 Outbox Pattern 같은 별도 설계가 필요하다

SSE 트래픽이 늘었을 때 풀 크기를 어떻게 튜닝할지(Prisma `connection_limit`)도 아직 정해두지 않았다

SSE 요청이 초당 10개 이상 들어오거나 DB connection timeout이 나기 시작하면 그때 다시 봐야 할 부분이다
