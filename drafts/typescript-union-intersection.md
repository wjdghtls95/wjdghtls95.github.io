---
title: "union, intersection 타입 — 조합의 미학"
description: "union, intersection 타입 — 조합의 미학"
date: "2026-07-31"
tags: ["learning"]
study: "학습/TypeScript/union-intersection.md"
---

# Union / Intersection Types
_Updated: 2026-06-24_

---

> [!note]- 용어 정리
> - **Discriminated Union(태그 유니온)**: 공통 리터럴 필드로 유니온 멤버를 구분하는 패턴
> - **타입 가드(Type Guard)**: 런타임에 유니온 타입을 좁히는 체크 (`typeof`, `instanceof`, `in`, 사용자 정의)
> - **`is` 키워드**: 사용자 정의 타입 가드의 반환 타입 선언 (`e is DomainException`)
> - **Exhaustive Check**: `never` 타입을 활용해 모든 케이스를 처리했는지 컴파일 타임에 검증

---

## Union (`|`) — "또는"

```ts
type StringOrNumber = string | number;
type Status = 'active' | 'inactive' | 'archived';
type NullableUser = User | null;
```

---

## Intersection (`&`) — "그리고"

```ts
type AdminUser = User & { permissions: string[] };
type WithTimestamp = { createdAt: Date; updatedAt: Date };
type AuditableUser = User & WithTimestamp;
```

---

## Union vs Intersection 비교

```ts
interface A { x: number }
interface B { y: string }

type UnionAB = A | B;
// x만 있거나, y만 있거나, 둘 다 있거나
// 공통 속성만 직접 접근 가능 — 타입 가드 없이 x, y 둘 다 접근 불가

type InterAB = A & B;
// x도 있고 y도 있어야 함 (둘 다 접근 가능)

const obj: InterAB = { x: 1, y: 'hello' }; // ✅
```

---

## Discriminated Union (태그 유니온)

공통 필드로 유니온 멤버를 구분. 타입 가드와 함께 쓰면 강력하다

```ts
type Shape =
  | { type: 'circle'; radius: number }
  | { type: 'square'; side: number }
  | { type: 'rectangle'; width: number; height: number };

function area(shape: Shape): number {
  switch (shape.type) {
    case 'circle':    return Math.PI * shape.radius ** 2;
    case 'square':    return shape.side ** 2;
    case 'rectangle': return shape.width * shape.height;
  }
}
```

JARVIS AI 에러 처리에서의 응용:

```ts
// apps/server/libs/common/filters/all-exception.filter.ts
// resolveErrorInfo()에서 instanceof로 분기
if (exception instanceof DomainException) { ... }
if (exception instanceof SystemException) { ... }
if (exception instanceof Prisma.PrismaClientKnownRequestError) { ... }
if (exception instanceof HttpException) { ... }
// unknown error fallback
```

---

## 타입 가드

### typeof

```ts
function format(value: string | number): string {
  if (typeof value === 'string') {
    return value.toUpperCase(); // string으로 좁혀짐
  }
  return value.toFixed(2); // number로 좁혀짐
}
```

### instanceof

```ts
function handleException(e: DomainException | SystemException) {
  if (e instanceof DomainException) {
    // DomainException으로 좁혀짐
  }
}
```

### in

```ts
function process(data: User | AdminUser) {
  if ('permissions' in data) {
    // AdminUser로 좁혀짐
    console.log(data.permissions);
  }
}
```

### 사용자 정의 타입 가드 (`is`)

```ts
function isDomainException(e: unknown): e is DomainException {
  return e instanceof DomainException;
}

// 사용
if (isDomainException(e)) {
  // e가 DomainException으로 좁혀짐
}
```

---

## Exhaustive Check

switch에 새 케이스를 추가해야 할 때 컴파일 에러로 알린다

```ts
type Action = 'create' | 'update' | 'delete';

function handle(action: Action): string {
  switch (action) {
    case 'create': return 'created';
    case 'update': return 'updated';
    case 'delete': return 'deleted';
    default:
      const _exhaustive: never = action; // 'archive' 추가 시 컴파일 에러
      return _exhaustive;
  }
}
```

---

## Anti-patterns

```ts
// ❌ 과도한 유니온 — 관리하기 어려움
type HugeUnion = TypeA | TypeB | TypeC | TypeD | TypeE | TypeF | TypeG;
// → Discriminated Union 패턴으로 리팩토링

// ❌ 교차 타입의 프리미티브 — never가 됨
type Impossible = string & number; // never
// 프리미티브는 교차 불가

// ❌ 타입 가드 없이 유니온 멤버 접근
function process(value: string | number) {
  value.toUpperCase(); // ❌ number에는 toUpperCase 없음
}
```

---

## Gotcha

- `null | undefined`는 TypeScript의 strictNullChecks 설정에서만 유니온으로 취급됨 — 설정 안 하면 모든 타입에 null/undefined 할당 가능
- `A & B`에서 동일한 키가 있으면 두 타입의 교차 타입이 됨. `{ x: string } & { x: number }`는 `{ x: never }` — 불가능한 타입

---

## 관련 개념

- [[interface-vs-type]] — union은 type으로
- [[conditional-types]] — 유니온 분배 조건부 타입
- [[generics]] — 제약에서 유니온 활용
- [[NestJS Exception Architecture]] — instanceof 분기 실전 적용
