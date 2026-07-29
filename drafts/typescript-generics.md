---
title: "TypeScript generics — 제대로 이해하기"
description: "타입 파라미터로 반복 코드를 줄이는 제네릭의 기본 개념부터 keyof 제약, 실무 Repository 패턴까지"
date: "2026-07-28"
tags: ["learning"]
study: "학습/TypeScript/generics.md"
rewritten: true
---

같은 로직인데 타입만 달라서 함수를 여러 개 만들어야 할 때가 있다. `getStringFirst`, `getNumberFirst`... 이걸 하나로 묶는 게 제네릭이다.

## 기본 개념

타입을 파라미터처럼 받는다. `<T>`에서 T는 타입 변수 — 관례상 T, U, K, V를 쓴다.

```ts
function identity<T>(arg: T): T {
  return arg;
}

identity<string>('hello'); // T = string, 명시적 지정
identity('hello');         // T = string, 추론
identity(42);              // T = number, 추론
```

대부분의 경우 TypeScript가 인수에서 T를 알아서 추론한다. `<string>`을 직접 쓸 일은 거의 없다.

## 함수 제네릭

```ts
// ✅ 배열의 첫 번째 요소 반환
function first<T>(arr: T[]): T | undefined {
  return arr[0];
}

// ✅ 두 값 교환 — 타입이 다를 수 있으니 T, U 둘 다 받음
function swap<T, U>(a: T, b: U): [U, T] {
  return [b, a];
}
```

반환 타입을 `T`로 고정하면 `any`와 달리 호출 시 타입 정보가 보존된다.

## 인터페이스/타입 제네릭

형태는 같고 데이터 타입만 다른 구조에 유용하다.

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

API 응답, 이벤트 페이로드처럼 반복되는 래퍼 구조에 자주 쓰인다.

## 타입 제약 (extends)

T를 완전히 열어두면 `item.id` 같은 속성 접근이 불가능하다. `extends`로 T가 만족해야 할 조건을 지정한다.

```ts
// ✅ T는 반드시 { id: string }을 가져야 함
function findById<T extends { id: string }>(items: T[], id: string): T | undefined {
  return items.find(item => item.id === id);
}

findById(users, '123'); // ✅ User는 id: string 보유
```

`keyof`와 조합하면 객체의 키를 타입 안전하게 다룰 수 있다.

```ts
// ✅ K는 T의 키여야 함
function getProperty<T, K extends keyof T>(obj: T, key: K): T[K] {
  return obj[key];
}

const user: User = { id: '1', email: 'a@b.com', name: 'John' };
getProperty(user, 'email'); // ✅ string
getProperty(user, 'xyz');   // ❌ 컴파일 에러 — 'xyz'는 User의 키가 아님
```

`K extends keyof T` 패턴은 TypeScript 내장 유틸리티 타입인 `Pick`에서도 같은 방식으로 쓰인다.

```ts
// Pick 내부 구현
type Pick<T, K extends keyof T> = { [P in K]: T[P]; };

// 실무 예시
conversationHistory: Pick<Message, 'role' | 'content'>[];
```

## 기본값 (Default Type Parameter)

T에 기본 타입을 지정할 수 있다.

```ts
interface Repository<T = unknown> {
  findAll(): Promise<T[]>;
}

const repo: Repository = ...;           // Repository<unknown>
const userRepo: Repository<User> = ...; // Repository<User>
```

타입 파라미터를 선택적으로 받아야 하는 공통 인터페이스 설계에 유용하다.

## 실무 패턴 — 제네릭 Repository

도메인별로 같은 CRUD 구조를 반복하지 않기 위해 제네릭 추상 클래스를 쓴다.

```ts
// ✅ 제네릭 기반 추상 Repository
abstract class BaseRepository<T, ID = string> {
  abstract findById(id: ID): Promise<T | null>;
  abstract findAll(): Promise<T[]>;
  abstract save(entity: T): Promise<T>;
}

// ✅ 각 도메인이 타입만 지정해서 상속
class UserRepository extends BaseRepository<User> {
  async findById(id: string): Promise<User | null> {
    return this.db.user.findUnique({ where: { id } });
  }
}
```

공통 로직은 `BaseRepository`에 두고, 타입별 구현만 서브클래스에서 담당한다.

## Anti-patterns

제네릭이 유용한 건 타입 정보를 유지하면서 재사용성을 높일 때다. 그 목적에 맞지 않으면 쓰지 않는 게 낫다.

```ts
// ❌ 불필요한 제네릭 — 타입이 항상 string이면 그냥 string
function logString<T extends string>(msg: T): void {
  console.log(msg);
}
// ✅
function log(msg: string): void {
  console.log(msg);
}

// ❌ 반환 타입에 any 사용
function process<T>(data: T): any { ... }
// ✅ 반환 타입도 T나 구체적인 타입으로

// ❌ 타입 파라미터 3개 초과 — 읽기가 어려워짐
function combine<A, B, C, D>(a: A, b: B, c: C, d: D): [A, B, C, D] { ... }
// ✅ 객체로 받는 게 더 명확
```

## 주의할 점
```ts
// ❌ T extends any — 모든 타입이 any를 extends하므로 제약이 없는 것과 동일, 코드 스멜
// 더 큰 문제: 이 안에서 as any를 쓰면 T의 타입 보호가 완전히 무너짐
function wrap<T extends any>(val: T): void {
(val as any).doesNotExist(); // 컴파일러 통과, 런타임 에러 가능
}

// ✅ T extends unknown — 제약 없음을 안전하게 표현, 직접 조작 불가
function wrap<T extends unknown>(val: T): void {
// unknown이므로 타입 좁히기 없이 val 조작 불가 → 실수 방지
}

// ✅ 제약이 없을 땐 그냥 T
function wrap<T>(val: T): void { ... }
```
