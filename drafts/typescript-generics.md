---
title: "TypeScript generics — 제대로 이해하기"
description: "TypeScript generics — 제대로 이해하기"
date: "2026-07-28"
tags: ["learning"]
study: "학습/TypeScript/generics.md"
---

# Generics
_Updated: 2026-06-24_

---

> [!note]- 용어 정리
> - **타입 파라미터(Type Parameter)**: `<T>` 처럼 타입을 변수처럼 받는 것. 관례상 T, U, K, V 사용
> - **타입 추론(Type Inference)**: 함수 호출 시 인수에서 T를 자동으로 파악하는 것
> - **타입 제약(Type Constraint)**: `T extends { id: string }` 처럼 T가 만족해야 할 조건
> - **keyof**: 객체 타입의 모든 키를 유니온으로 반환하는 연산자

---

## 기본 개념

타입을 파라미터처럼 받아서 재사용 가능한 타입/함수/클래스를 만든다

```ts
function identity<T>(arg: T): T {
  return arg;
}

identity<string>('hello'); // T = string, 명시적 지정
identity('hello');         // T = string, 추론
identity(42);              // T = number, 추론
```

---

## 함수 제네릭

```ts
// ✅ 배열의 첫 번째 요소 반환
function first<T>(arr: T[]): T | undefined {
  return arr[0];
}

// ✅ 두 값 교환
function swap<T, U>(a: T, b: U): [U, T] {
  return [b, a];
}
```

---

## 인터페이스/타입 제네릭

```ts
// ✅ 페이지네이션 응답
interface PaginatedResult<T> {
  items: T[];
  total: number;
  page: number;
  pageSize: number;
}

type UserPage = PaginatedResult<User>;
type ConversationPage = PaginatedResult<Conversation>;
```

---

## 타입 제약 (extends)

T가 특정 타입을 만족해야 한다는 제약

```ts
// T는 반드시 { id: string }을 가져야 함
function findById<T extends { id: string }>(items: T[], id: string): T | undefined {
  return items.find(item => item.id === id);
}

findById(users, '123');         // ✅ User는 id: string 보유
getProperty(user, 'xyz');       // ❌ 'xyz'는 User의 키가 아님 — 컴파일 에러
```

```ts
// K는 T의 키여야 함
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

const user: User = { id: '1', email: 'a@b.com', name: 'John' };
getProperty(user, 'email'); // ✅ string
```

---

## JARVIS AI에서 실제 사용

### BaseRepository — 제네릭 Repository 패턴

`apps/server/libs/common/repositories/base.repository.ts`에서 제네릭을 활용한다

```ts
// TransactionHost가 제네릭 타입을 받음
type PrismaTransactionHost = TransactionHost<TransactionalAdapterPrisma<DatabaseService>>;

export abstract class BaseRepository {
  constructor(protected readonly txHost: PrismaTransactionHost) {}

  protected get db() {
    return this.txHost.tx;
  }
}
```

각 도메인 Repository가 이를 상속:

```ts
// apps/server/src/user/repositories/user.repository.ts
@Injectable()
export class UserRepository extends BaseRepository {
  constructor(txHost: PrismaTransactionHost) {
    super(txHost);
  }

  async findById(id: string): Promise<User | null> {
    return this.db.user.findUnique({ where: { id } });
  }
}
```

### Pick 타입 + 제네릭 응용

inference 클라이언트에서 Message 타입의 일부만 전달:

```ts
// apps/server/src/inference/inference.client.ts
conversationHistory: Pick<Message, 'role' | 'content'>[];
```

`Pick<T, K extends keyof T>`의 K가 제네릭 제약을 사용하는 패턴

---

## 기본값 (Default Type Parameter)

```ts
// T 기본값 지정
interface Repository<T = unknown> {
  findAll(): Promise<T[]>;
}

const repo: Repository = ...;      // Repository<unknown>
const userRepo: Repository<User> = ...; // Repository<User>
```

---

## Anti-patterns

```ts
// ❌ 불필요한 제네릭 — 타입이 항상 string이면 그냥 string
function logString<T extends string>(msg: T): void {
  console.log(msg);
}
// → function log(msg: string): void

// ❌ 반환 타입에 any 사용
function process<T>(data: T): any { ... }
// → 반환 타입도 T나 구체적인 타입으로

// ❌ 타입 파라미터 3개 초과
function combine<A, B, C, D>(a: A, b: B, c: C, d: D): [A, B, C, D] { ... }
// → 객체로 받는 게 더 명확
```

---

## Gotcha

- `T extends any` 는 사실상 제약이 없는 것 — `unknown`이 더 안전
- 클래스 제네릭에서 `new (this as any)()` 패턴은 타입 정보를 잃음 — 실제 JARVIS AI 코드는 `BaseResponseDto.of()` 패턴을 더 명시적으로 작성
- `Record<K, V>` 는 내부적으로 `{ [P in K]: V }` Mapped Type — [[mapped-types]] 참조

---

## 관련 개념

- [[conditional-types]] — T extends U ? X : Y 패턴
- [[mapped-types]] — [K in keyof T] 패턴
- [[utility-types]] — 내장 유틸리티 타입들
- [[interface-vs-type]] — 제네릭과 함께 쓰는 interface
