---
title: "NestJS Integration Testing — 진짜 DB로 테스트하는 법"
description: "AppModule을 한 번만 컴파일하고 트랜잭션 롤백으로 격리하는 통합 테스트 구조"
date: "2026-09-14"
tags: ["NestJS"]
qa_done: true
rewritten: true
---

유닛 테스트에서 DB고 Redis고 다 mock으로 갈아치우면 통과율은 높아지는데 실제 버그는 못 잡는다

쿼리 조건 하나 틀려도 mock이 알아서 원하는 값을 뱉어주니까 테스트가 초록불이다

그래서 실제 DB를 붙이는 통합 테스트가 필요한데, 문제는 속도다

spec마다 AppModule을 새로 컴파일하면 이렇게 된다

```ts
beforeAll(async () => {
  const module = await Test.createTestingModule({ imports: [AppModule] }).compile();
  // 컴파일에만 대략 10초
});

afterAll(async () => {
  await module.close();
});
```

spec 파일이 30개면 컴파일만 5분 넘게 걸린다

## 어떻게 해결하나

핵심은 두 가지로 나뉜다

- AppModule 컴파일은 프로세스당 딱 한 번
- 각 테스트는 트랜잭션으로 감싸고 끝나면 롤백

```ts
// 파일 import 시점에 한 번만 실행되는 Promise
export const testAppModule: Promise<TestAppContext> = (async () => {
  // AppModule 컴파일 한 번
  // 테스트용 트랜잭션 헬퍼 초기화 한 번
})();

beforeEach(() => TestTransaction.begin());   // savepoint 시작
afterEach(() => TestTransaction.rollback()); // 롤백, DB 상태 원복
```

Promise를 모듈 스코프에 선언해두면 이 파일을 import하는 모든 spec이 같은 인스턴스를 공유한다

단, `--runInBand` 옵션이 필수다

병렬 실행하면 워커마다 별도 프로세스라 Promise도 각자 만들어지고, 결국 AppModule을 워커 수만큼 다시 컴파일하게 된다

## 트랜잭션 프록시가 하는 일

싱글톤 모듈을 만들 때 실제 DB 클라이언트 대신 트랜잭션 프록시 클라이언트를 주입한다 (`@chax-at/transactional-prisma-testing` 같은 라이브러리가 이 프록시를 만들어줌)

```ts
const helper = new PrismaTestingHelper(prisma);
TestTransaction.init(helper);

const builder = Test.createTestingModule({ imports: [AppModule] })
  .overrideProvider(DatabaseService)
  .useValue(helper.getProxyClient())     // 실제 DB 대신 트랜잭션 프록시
  .overrideProvider(InferenceClient)
  .useValue(inferenceClientMock)         // 외부 API 호출은 mock
```

흐름은 이렇다

```
DatabaseService를 프록시로 교체 등록
  ↓
테스트 코드에서 module.get(DatabaseService)
  ↓
실제 DB가 아닌 트랜잭션 프록시 반환
  ↓
Factory가 이 프록시로 INSERT
  ↓
모든 쿼리가 테스트 savepoint 안에서 실행
  ↓
afterEach: rollback → 데이터 전부 사라짐
```

`new DatabaseService()`를 직접 생성해서 쓰면 이 프록시를 안 거치니까 트랜잭션 밖에서 진짜로 INSERT된다

override 안 하면 mock을 아무리 잘 짜도 소용없다

## Factory로 테스트 데이터 만들기

매 테스트마다 필요한 엔티티를 직접 만들면 코드가 길어지고 중복도 심하다

```ts
export class ConversationFactory {
  static async create(
    module: TestingModule,
    userId: string,
    overrides: Partial<{ title: string | null; status: ConversationStatus }> = {},
  ) {
    const db = module.get(DatabaseService); // 트랜잭션 프록시

    return db.conversation.create({
      data: { userId, title: null, status: 'ACTIVE', ...overrides },
    });
  }
}
```

Factory도 `module.get(DatabaseService)`로 DB를 가져오니까 여기서 만든 데이터 역시 테스트 트랜잭션 안에 갇힌다

테스트 끝나면 자동으로 사라진다는 뜻

## 뭘 테스트해야 하나

API가 200이나 201을 반환하는지는 코드만 읽어도 알 수 있다

의미 있는 건 비즈니스 조건이 갈리는 지점이다

```ts
// ❌ 코드 읽으면 알 수 있는 것
it('conversation 생성 → 201 반환', ...)

// ✅ 실제 비즈니스 변수가 달라질 때의 분기
it('ARCHIVED conversation은 목록에서 제외됨', ...)
it('다른 유저의 conversation → FORBIDDEN', ...)
it('isIncomplete 메시지는 inference context에서 제외됨', ...)
it('다른 유저 memory 삭제 → FORBIDDEN 아닌 NOT_FOUND', ...)
```

마지막 케이스가 특히 그렇다

리소스가 없는 것과 권한이 없는 것을 같은 응답으로 처리하는 이유는 존재 여부 자체를 노출하지 않기 위해서다

테스트 이름을 시나리오로 쓰면 구현이 바뀌어도 테스트 의도는 안 바뀐다

## mock 상태 공유 막기

BullMQ 큐나 외부 API 클라이언트는 mock으로 대체하는데, 이 mock들이 테스트 간에 상태를 공유하면 안 된다

```ts
beforeEach(() => {
  jest.clearAllMocks();
  TestTransaction.begin();
});
```

`inferenceClientMock.extractMemories.mockResolvedValue(...)` 처럼 특정 테스트에서만 동작을 바꾸는 경우, clearAllMocks 이후 해당 테스트 안에서 다시 설정해야 한다

## 삽질한 것

- `--runInBand` 빼먹으면 싱글톤 공유가 깨지고 속도도 그대로 느려짐, 테스트 스크립트에 이 옵션이 있는지부터 확인
- 스키마 바꾸고 테스트 DB에 반영 안 함, 마이그레이션 도구로 테스트용 DB URL 지정해서 스키마 push 따로 해줘야 함
- 트랜잭션 헬퍼 기본 timeout이 짧아서 디버거로 브레이크포인트 걸어두면 타임아웃으로 트랜잭션이 강제 종료됨, 옵션으로 timeout 값을 늘려야 디버깅 가능
- `jest.clearAllMocks()` 빠뜨리면 이전 테스트의 mockResolvedValue가 다음 테스트까지 남아서 엉뚱한 데서 실패함
