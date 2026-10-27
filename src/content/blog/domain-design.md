---
title: "도메인 설계 — 어떤 기준으로 모듈을 나눠야 하는가"
description: "NestJS 모듈을 도메인 단위로 나누고, 단방향 의존성과 이벤트·큐로 순환 참조를 피하는 기준 정리"
date: "2026-10-26"
tags: ["아키텍처"]
qa_done: true
rewritten: true
---

모듈을 나누는 일보다 어려운 건 나눈 뒤에 의존성 방향을 지키는 일이다
A가 B를 쓰고 B가 다시 A를 쓰기 시작하면 컴파일 에러나 예측하기 어려운 런타임 동작으로 이어진다

JARVIS AI 서버는 이걸 "도메인마다 책임을 하나씩 갖고, 의존은 한 방향으로만 흐른다"는 규칙으로 막는다

## 도메인 목록과 책임

`app.module.ts`에 등록된 도메인은 이렇게 나뉜다

| 도메인 | 책임 | Prisma 모델 |
|--------|------|-------------|
| Auth | JWT 발급, OAuth, Refresh Token Rotation | RefreshToken, Account |
| User | 유저 프로필, 계정 삭제 | User, Account, Device |
| Conversation | 대화 CRUD, 상태 관리 | Conversation |
| Message | 메시지 저장, SSE 스트리밍 | Message |
| Memory | 장기 기억 CRUD, RAG 검색 | Memory |
| Queue | BullMQ worker 등록 | 없음 |
| Calendar | Google Calendar API 연동 | CalendarEvent |
| Alert | FCM/APNs 알림 발송 | Alert |
| Task | 할일 관리, 리마인더 | Task |
| Briefing | 아침 브리핑 cron | BriefingSetting |
| Routine | 루틴 패턴 감지 | RoutineFeedback |

도메인마다 Prisma 모델과 enum도 자기 것만 가진다
`Plan`은 User, `Provider`는 Auth, `MemoryCategory`는 Memory 하는 식이다

## 단방향 의존성

![다이어그램](/diagrams/domain-design-1.svg)

규칙은 단순하다

- `auth → user` ✅ Auth가 User를 참조
- `user → auth` ❌ User가 Auth를 역참조

화살표를 뒤집고 싶어지는 순간은 코드 문제가 아니라 도메인 경계를 다시 봐야 한다는 신호다
같은 레이어끼리 `Service → Service`로 얽히는 것도 피하고, 필요하면 아래의 이벤트나 큐로 분리한다

## 순환 참조가 생기면 이 순서로 푼다

1. **도메인 경계 재검토**: 두 모듈이 사실은 같은 도메인인지, 단방향으로 바꿀 수 있는지 본다
2. **공통 로직을 `libs/common`으로 추출**: 양쪽이 필요로 하는 부분만 따로 뺀다
3. **EventEmitter2로 분리**: 약한 결합이 필요한 도메인 간 통신은 이벤트로 바꾼다
4. **`forwardRef()`**: 위 셋이 다 안 될 때만 쓰는 최후 수단이다

```ts
// UserService 상호 의존 불가피, 리팩토링 예정
@Inject(forwardRef(() => AuthService))
```

`forwardRef()`는 문제를 푸는 게 아니라 미루는 것에 가깝다
그래서 쓸 때는 리팩토링 예정이라는 주석을 반드시 남기는 규칙을 둔다

## 도메인 간 통신은 세 가지

### 직접 의존

방향이 정해져 있고 결과를 바로 받아야 할 때 쓴다

```ts
// ✅ MessageService → MemoryService (단방향)
@Injectable()
export class MessageService {
  constructor(private readonly memoryService: MemoryService) {}
}
```

### 이벤트

보내는 쪽이 받는 쪽을 몰라도 될 때 쓴다

```ts
// 발생: 누가 받는지 모름
this.eventEmitter.emit('user.deleted', { userId });

// 수신: 직접 의존 없음
@OnEvent('user.deleted')
async handleUserDeleted(payload: { userId: string }) { ... }
```

### 큐

응답을 기다릴 필요 없는 비동기 작업에 쓴다

```ts
// 메시지 처리 후 메모리 추출 잡을 enqueue
await this.memoryExtractQueue.add(MEMORY_EXTRACT_JOB, { userId, conversationId, messageIds });
```

실제 처리는 QueueModule의 worker가 맡는다
MessageModule은 큐에 넣기만 하니까 worker 쪽 도메인과 직접 의존이 생기지 않는다

## barrel export를 금지하는 이유

`libs/common`을 가져올 때는 `@libs/common` 한 줄 대신 명시적인 경로를 쓴다

```ts
// ❌ barrel export
import { BaseRepository } from '@libs/common';

// ✅ 명시적 경로
import { BaseRepository } from '@libs/common/repositories/base.repository';
import { DomainException } from '@libs/common/exceptions/domain.exception';
```

barrel은 한 파일이 모든 걸 다시 내보내는 구조라서 순환 참조가 어디서 생겼는지 찾기 어려워진다
트리 쉐이킹도 방해한다

## 새 도메인을 추가할 때

1. `prisma/schema.prisma`에 모델과 enum 추가
2. `npx prisma generate`, `prisma db push`
3. `apps/server/src/{domain}/` 아래에 module, service, controller(HTTP API가 있다면), `repositories/{domain}.repository.ts` 생성
4. `app.module.ts`에 import 추가
5. 의존하는 도메인 모듈에서 필요한 Service가 export되어 있는지 확인

스키마를 고친 뒤 `prisma generate`를 빼먹으면 코드에서 새 모델이 보이지 않는다

## CoreModule 위에 쌓이는 구조

`CoreModule`이 `ConfigModule`, `ClsModule`, `DatabaseModule` 같은 글로벌 인프라를 맡고, 나머지 도메인은 그 위에서 단방향으로만 쌓인다
의존 방향이 꼬이면 `forwardRef()`로 덮기 전에 경계부터 다시 긋는 쪽이 원칙이다
