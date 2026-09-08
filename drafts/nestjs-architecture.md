---
title: "NestJS 아키텍처 — Controller, Service, Repository가 어떻게 연결되나"
description: "Module, Controller, Service, Repository 레이어가 DI로 어떻게 연결되는지 JARVIS 코드로 정리"
date: "2026-09-09"
tags: ["NestJS"]
qa_done: true
rewritten: true
---

Express나 Fastify만 쓰면 코드 구조가 딱히 없다

파일을 어디에 두든 동작은 하니까, 프로젝트가 커질수록 어떤 로직이 어디 있는지 찾기가 점점 어려워진다

NestJS는 여기에 Module, Controller, Service, Repository라는 레이어를 강제하고, 그 사이 의존성을 DI 컨테이너가 자동으로 주입한다

각 클래스의 역할이 명확해지고, 테스트할 때 의존성을 갈아끼우기도 쉬워진다

## 어떻게 동작하나

Module이 컨테이너 역할을 한다

Controller, Service, Repository를 등록하고, DI 컨테이너가 이들 사이 의존성을 자동으로 주입하는 구조

```
AppModule
 ├─ MemoryModule
 │   ├─ MemoryController  (HTTP 요청 처리)
 │   ├─ MemoryService     (비즈니스 로직)
 │   └─ MemoryRepository  (DB 접근)
 ├─ AuthModule
 └─ MessageModule
```

레이어는 한 방향으로만 의존한다

Controller → Service → Repository → DB

### Module

관련 클래스들을 하나의 단위로 묶는 컨테이너

- `imports`: 다른 모듈에서 가져올 것
- `controllers`: HTTP 요청을 처리할 클래스 목록
- `providers`: DI 컨테이너에 등록할 클래스 목록 (Service, Repository 등)

```typescript
@Module({
  imports: [TypeOrmModule.forFeature([User])],
  controllers: [UsersController],
  providers: [UsersService],
})
export class UsersModule {}
```

### Controller

HTTP 요청을 받아서 Service에게 위임하는 레이어

비즈니스 로직은 여기 없다

요청 파싱, 응답 포맷, 인증 체크 정도만 담당

```typescript
@Controller('conversations/:conversationId/messages')
export class MessageController {
  constructor(
    private readonly messageService: MessageService,
    private readonly conversationService: ConversationService,
  ) {}

  @Post()
  async handleSendMessage(
    @CurrentUser() user: User,
    @Param('conversationId') conversationId: string,
    @Body() dto: SendMessageDto,
  ) {
    await this.conversationService.getConversationOrThrow(user.id, conversationId);
    // 이후 로직은 Service에 위임
  }
}
```

소유권 체크와 요청 파싱까지만 Controller가 하고, 실제 로직은 Service로 넘긴다

### Service

비즈니스 로직 레이어, Controller와 Repository 사이에 있다

트랜잭션 관리, 도메인 규칙 적용, 외부 서비스 호출이 여기 모인다

다른 Service를 직접 주입하는 건 피하는 게 좋다

같은 레이어끼리 얽히기 시작하면 순환 참조로 이어진다

```typescript
@Injectable()
export class MemoryService {
  constructor(private readonly memoryRepository: MemoryRepository) {}

  async deleteMemory(userId: string, id: string): Promise<void> {
    const memory = await this.memoryRepository.findOneByUserIdAndId(userId, id);
    if (!memory) throw new DomainException(DOMAIN_ERRORS.MEMORY_NOT_FOUND);
    await this.memoryRepository.delete(id, userId);
  }
}
```

### Repository

DB 접근만 담당하는 레이어

공통 베이스 클래스를 만들어두면 트랜잭션 컨텍스트를 레이어마다 신경 쓸 필요가 없어진다

```typescript
export abstract class BaseRepository {
  constructor(protected readonly txHost: PrismaTransactionHost) {}

  protected get db() {
    return this.txHost.tx;  // 트랜잭션 중이면 tx, 아니면 일반 prisma client
  }
}

export class RefreshTokenRepository extends BaseRepository {
  delete(token: string): Promise<RefreshToken> {
    return this.db.refreshToken.delete({ where: { token } });
  }
}
```

`txHost.tx`가 활성 트랜잭션 여부에 따라 알아서 tx client나 일반 client를 돌려준다

`@Transactional()` 데코레이터랑 묶이면 Repository 코드는 트랜잭션을 신경 쓸 필요가 없어짐

## JARVIS에서 실제로 어떻게 썼나

JARVIS 서버는 도메인별로 모듈을 쪼갰다

Auth, User, Conversation, Message, Memory, Calendar, Alert, Task, Briefing, Routine

이렇게 나눠두면 한 도메인의 변경이 다른 도메인 코드를 건드리지 않는다

공통 인프라(설정, DB 연결, 캐시)는 별도 모듈로 묶어서 다른 모든 모듈이 가져다 쓰는 구조로 뺐다

Config, Database 관련 설정을 매 모듈마다 반복하지 않아도 된다

## 삽질한 것

**글로벌 필터, 파이프, 가드는 DI 밖이라 주입이 안 된다**

```typescript
// 이렇게 쓰면 DI 컨테이너 밖에서 수동으로 인스턴스를 만드는 거라
app.useGlobalFilters(new AllExceptionFilter())
```

`AllExceptionFilter`가 다른 Provider를 주입받아야 하는 상황이면 이 방식으로는 안 된다

`APP_FILTER`, `APP_PIPE`, `APP_GUARD` 토큰으로 등록하면 DI 컨테이너가 생성을 맡아준다

```typescript
{
  provide: APP_FILTER,
  useClass: AllExceptionFilter,
}
```

**같은 레이어끼리 주입하면 순환 참조가 생긴다**

Service A가 Service B를 주입받고, Service B가 다시 Service A를 주입받으면 NestJS가 인스턴스를 못 만든다

해결 순서는 이렇게 잡았다

- 도메인 경계 재검토, 두 Service가 정말 서로 알아야 하는지 확인
- 공통 로직이면 별도 모듈로 추출
- 이벤트로 풀리면 EventEmitter로 분리
- 그래도 안 풀리면 `forwardRef()` 최후 수단
