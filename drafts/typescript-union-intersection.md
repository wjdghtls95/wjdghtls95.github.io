---
title: "union, intersection 타입 — 조합의 미학"
description: "유니온과 인터섹션의 차이부터 Discriminated Union, 타입 가드, Exhaustive Check까지 실전 예제로 정리"
date: "2026-07-31"
tags: ["TypeScript"]
study: "학습/TypeScript/union-intersection.md"
rewritten: true
---

TypeScript에서 타입을 조합하는 방법은 두 가지다. `|`로 "이거 또는 저거"를 표현하거나, `&`로 "이것과 저것 모두"를 표현한다.

## Union (`|`) — "또는"

하나의 값이 여러 타입 중 하나일 수 있을 때 쓴다.

```ts
type StringOrNumber = string | number;
type Status = 'active' | 'inactive' | 'archived';
type NullableUser = User | null;
```

유니온 타입에서는 모든 멤버에 공통으로 있는 속성만 타입 가드 없이 접근할 수 있다. 특정 타입에만 있는 속성에 접근하려면 타입 가드가 필요하다.

## Intersection (`&`) — "그리고"

두 타입의 속성을 모두 가져야 할 때 쓴다.

```ts
type AdminUser = User & { permissions: string[] };
type WithTimestamp = { createdAt: Date; updatedAt: Date };
type AuditableUser = User & WithTimestamp;
```

`AdminUser`는 `User`의 모든 필드 + `permissions` 배열을 전부 가져야 한다.

## Union vs Intersection

헷갈리기 쉬운 부분이다.

```ts
interface A { x: number }
interface B { y: string }

type UnionAB = A | B;
// x만 있거나, y만 있거나, 둘 다 있어도 됨
// 타입 가드 없이는 공통 속성만 접근 가능

type InterAB = A & B;
// x와 y 둘 다 있어야 함

const obj: InterAB = { x: 1, y: 'hello' }; // ✅
```

유니온은 "하나 이상", 인터섹션은 "전부"다.

## Discriminated Union

유니온 멤버가 많아질수록 각 케이스를 어떻게 구분할지가 문제가 된다. 공통 리터럴 필드(`type`, `kind` 등)를 두면 TypeScript가 switch 블록 안에서 타입을 자동으로 좁혀준다.

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

JARVIS AI 프로젝트에서도 같은 패턴이 나온다. 예외 처리 필터에서 `instanceof`로 에러 종류를 분기한다:

```ts
// apps/server/libs/common/filters/all-exception.filter.ts
if (exception instanceof DomainException) { ... }
if (exception instanceof SystemException) { ... }
if (exception instanceof Prisma.PrismaClientKnownRequestError) { ... }
if (exception instanceof HttpException) { ... }
// unknown error fallback
```

각 예외 클래스가 리터럴 필드 대신 클래스 계층이 "태그" 역할을 하는 셈이다.

## 타입 가드

유니온 타입을 특정 타입으로 좁히는 방법이다.

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

반복되는 타입 체크 로직을 함수로 분리할 때 쓴다. 반환 타입을 `boolean` 대신 `e is DomainException`으로 선언하면, 이 함수가 true를 반환할 때 TypeScript가 타입을 좁혀준다.

```ts
// ❌ boolean 반환 — 타입 좁히기 안 됨
function check(e: unknown): boolean {
  return e instanceof DomainException;
}

// ✅ is 반환 — 타입 좁히기 됨
function isDomainException(e: unknown): e is DomainException {
  return e instanceof DomainException;
}

if (isDomainException(e)) {
  // e가 DomainException으로 좁혀짐
}
```

## Exhaustive Check

`never`를 활용하면 유니온에 새 케이스를 추가했는데 처리하지 않으면 컴파일 에러로 잡아준다.

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

`Action`에 `'archive'`를 추가하면 default 블록에서 `action`이 `'archive'` 타입이 되어 `never`에 할당할 수 없다는 에러가 난다. switch를 업데이트하라는 신호다.

## 주의할 점

**프리미티브 교차 타입은 `never`가 된다**

```ts
// ❌
type Impossible = string & number; // never
```

`string`이면서 동시에 `number`인 값은 없다.

**같은 키가 다른 타입이면 마찬가지다**

```ts
// ❌
type Result = { x: string } & { x: number }; // { x: never }
```

**과도한 유니온은 리팩토링 대상**

```ts
// ❌
type HugeUnion = TypeA | TypeB | TypeC | TypeD | TypeE | TypeF | TypeG;
// → Discriminated Union 패턴으로 정리
```

**`strictNullChecks` 주의**

`null | undefined`는 `strictNullChecks`가 켜져 있어야 유니온으로 취급된다. 꺼져 있으면 모든 타입에 `null`과 `undefined`가 할당 가능해진다.
