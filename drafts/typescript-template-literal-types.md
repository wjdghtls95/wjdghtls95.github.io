---
title: "Template Literal Types"
description: "문자열 패턴을 타입 레벨에서 강제하는 Template Literal Types의 실전 활용법"
date: "2026-07-31"
tags: ["learning"]
study: "학습/TypeScript/template-literal-types.md"
rewritten: true
---

# Template Literal Types

API 엔드포인트는 반드시 `/api/`로 시작해야 한다는 규칙이 있다. 코드 리뷰마다 잡기엔 번거롭다.

```ts
type ApiEndpoint = `/api/${string}`;

function callApi(endpoint: ApiEndpoint) { /* ... */ }

callApi('/api/users');    // ✅
callApi('/users');        // ❌ 타입 오류 — /api/ 로 시작해야 함
```

Template Literal Types는 JS의 문자열 보간(`` `Hello, ${name}` ``)을 타입 레벨로 올린 것이다. TypeScript 4.1에서 도입됐다.

## 기본 문법

```ts
type Greeting = `Hello, ${string}`;
type WelcomeMsg = `Hello, ${'World' | 'NestJS'}`; // 'Hello, World' | 'Hello, NestJS'
```

유니온을 넣으면 조합된 유니온이 나온다.

## 내장 문자열 조작 유틸리티

```ts
type U = 'hello world';

type A = Uppercase<U>;    // 'HELLO WORLD'
type B = Lowercase<U>;    // 'hello world'
type C = Capitalize<U>;   // 'Hello world'
type D = Uncapitalize<U>; // 'hello world'
```

Mapped Types에서 키 이름을 변환할 때 자주 쓰인다.

## 실전 패턴

### 이벤트 이름 타입

```ts
type EventName<T extends string> = `${T}Created` | `${T}Updated` | `${T}Deleted`;

type UserEvent = EventName<'User'>;         // 'UserCreated' | 'UserUpdated' | 'UserDeleted'
type ConvEvent = EventName<'Conversation'>; // 'ConversationCreated' | ...
```

반복되는 이벤트 이름 패턴을 제네릭으로 한 번에 정의할 수 있다.

### Getter/Setter 자동 생성

Mapped Types의 `as` 절과 결합하면 키 이름 자체를 변환할 수 있다.

```ts
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};

type Setters<T> = {
  [K in keyof T as `set${Capitalize<string & K>}`]: (value: T[K]) => void;
};
```

`Capitalize<string & K>` 패턴이 자주 보인다. `K`는 `string | number | symbol`이 될 수 있어서 `string & K`로 string인 키만 걸러내는 것이다.

### 도메인 에러 코드 강제

```ts
type AuthErrorCode = `AUTH_${string}`;
type UserErrorCode = `USER_${string}`;
type SystemErrorCode = `SYS_${string}`;

type ErrorCode = AuthErrorCode | UserErrorCode | SystemErrorCode;
```

`AUTH_001`, `USER_001`, `SYS_001` 같은 형식만 허용된다.

JARVIS AI에서는 에러 코드를 `DOMAIN_ERRORS` 상수로 관리하는데, 새 에러를 추가할 때 이 타입으로 형식을 컴파일 타임에 강제한다.

### 도메인 이벤트 이름

```ts
// EventEmitter2 이벤트 이름 — 'user.created', 'memory.saved' 형식만 허용
type DomainEvent = `${string}.${string}`;
```

## infer와 결합

Conditional Types의 `infer`와 결합하면 패턴에서 특정 부분을 추출할 수 있다.

```ts
type ExtractPrefix<T> = T extends `${infer Prefix}_${string}` ? Prefix : never;

type Result = ExtractPrefix<'AUTH_001'>; // 'AUTH'
type None   = ExtractPrefix<'invalid'>;  // never
```

## 한계

유니온 조합이 많아지면 TypeScript 성능이 크게 저하된다.

```ts
// ❌ 조합 폭발 — 유니온 멤버가 많으면 타입 체크가 매우 느려짐
type AllCombinations<T extends string> = `${T}-${T}-${T}`;

// ✅ 실용적인 범위 내에서 사용
type Endpoint = `/api/${string}`;
```

TypeScript 4.1 이상 필요하다. `tsconfig.json`의 `target` 설정과 무관하게 TS 컴파일러 버전이 중요하다.
