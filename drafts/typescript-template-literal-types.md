---
title: "Template Literal Types"
description: "Template Literal Types"
date: "2026-07-31"
tags: ["learning"]
study: "학습/TypeScript/template-literal-types.md"
---

# Template Literal Types
_Updated: 2026-06-24_

---

> [!note]- 용어 정리
> - **Template Literal**: `` `Hello, ${name}` `` 같은 JS 문자열 보간 문법을 타입 레벨로 올린 것
> - **Capitalize**: `'hello'` → `'Hello'`. 내장 문자열 조작 유틸리티
> - **Uppercase / Lowercase**: `'hello'` → `'HELLO'` / `'HELLO'` → `'hello'`
> - **조합 폭발(Combination Explosion)**: 유니온 조합이 많아지면 컴파일 성능 저하

---

## 기본 문법

TypeScript 4.1+. 문자열 템플릿으로 타입을 만든다

```ts
type Greeting = `Hello, ${string}`;
type WelcomeMsg = `Hello, ${'World' | 'NestJS'}`; // 'Hello, World' | 'Hello, NestJS'
```

---

## 내장 문자열 조작 유틸리티

```ts
type U = 'hello world';

type A = Uppercase<U>;    // 'HELLO WORLD'
type B = Lowercase<U>;    // 'hello world'
type C = Capitalize<U>;   // 'Hello world'
type D = Uncapitalize<U>; // 'hello world'
```

---

## 실전 패턴

### 이벤트 이름 타입

```ts
type EventName<T extends string> = `${T}Created` | `${T}Updated` | `${T}Deleted`;

type UserEvent = EventName<'User'>;         // 'UserCreated' | 'UserUpdated' | 'UserDeleted'
type ConvEvent = EventName<'Conversation'>; // 'ConversationCreated' | ...
```

### Getter/Setter 자동 생성 (Mapped Types와 결합)

```ts
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K];
};

type Setters<T> = {
  [K in keyof T as `set${Capitalize<string & K>}`]: (value: T[K]) => void;
};
```

### API 경로 타입

```ts
type ApiEndpoint = `/api/${string}`;

function callApi(endpoint: ApiEndpoint) { ... }

callApi('/api/users');    // ✅
callApi('/users');        // ❌ 타입 오류 — /api/ 로 시작해야 함
```

---

## JARVIS AI에서의 활용

### 에러 코드 타입 강제

```ts
// 도메인별 에러 코드 형식 강제
type AuthErrorCode = `AUTH_${string}`;
type UserErrorCode = `USER_${string}`;
type SystemErrorCode = `SYS_${string}`;

type ErrorCode = AuthErrorCode | UserErrorCode | SystemErrorCode;
// 'AUTH_001', 'USER_001', 'SYS_001' 형식만 허용
```

실제 JARVIS AI에서 에러 코드는 `DOMAIN_ERRORS` 상수로 관리하지만, 새 에러 추가 시 코드 형식을 이 타입으로 검증할 수 있다

### 도메인 이벤트 이름

```ts
// EventEmitter2 이벤트 이름 타입 안전하게 관리
type DomainEvent = `${string}.${string}`; // 'user.created', 'memory.saved' 형식
```

---

## 한계

```ts
// ❌ 너무 복잡하면 TypeScript 성능 저하
type AllCombinations<T extends string> = `${T}-${T}-${T}`;
// 조합 폭발 — 유니온 멤버가 많으면 타입 체크 매우 느려짐

// ✅ 실용적인 범위 내에서만
type Method = 'get' | 'post' | 'put' | 'delete';
type Endpoint = `/api/${string}`; // OK
```

---

## Gotcha

- TypeScript 4.1 이상 필요 — `tsconfig.json`에서 `"target"` 과 관계없이 TS 버전이 중요
- `Capitalize<string & K>` 패턴: `K`는 `string | number | symbol`이 될 수 있어서 `& K`로 string만 추출

---

## 관련 개념

- [[mapped-types]] — as 절에서 template literal 활용
- [[generics]] — 타입 파라미터와 결합
- [[union-intersection]] — 유니온 멤버와 template literal 조합
