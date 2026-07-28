---
title: "TypeScript 유틸리티 타입 실전 (Partial, Pick, Omit, Required)"
description: "TypeScript 유틸리티 타입 실전 (Partial, Pick, Omit, Required)"
date: "2026-07-28"
tags: ["learning"]
study: "학습/TypeScript/utility-types.md"
---

# Utility Types
_Updated: 2026-06-24_

---

> [!note]- 용어 정리
> - **유틸리티 타입**: TypeScript 내장 제네릭 타입. Mapped Types와 Conditional Types로 구현되어 있음
> - **shallow**: Partial 등이 최상위 레벨만 변환하고 중첩 객체는 변환하지 않는 특성
> - **Awaited**: Promise를 재귀적으로 unwrap해서 resolved 타입 추출

---

## 자주 쓰는 것들 한눈에

| 유틸리티 | 하는 일 | 예시 |
|---------|---------|------|
| `Partial<T>` | 모든 프로퍼티 optional | `Partial<User>` |
| `Required<T>` | 모든 프로퍼티 required | `Required<UpdateUserDto>` |
| `Readonly<T>` | 모든 프로퍼티 readonly | `Readonly<Config>` |
| `Pick<T, K>` | 일부만 선택 | `Pick<User, 'id' \| 'email'>` |
| `Omit<T, K>` | 일부만 제외 | `Omit<User, 'passwordHash'>` |
| `Record<K, V>` | 키-값 맵 | `Record<string, number>` |
| `Extract<T, U>` | 유니온에서 겹치는 것만 | `Extract<'a' \| 'b', 'a'>` |
| `Exclude<T, U>` | 유니온에서 제외 | `Exclude<'a' \| 'b', 'a'>` |
| `NonNullable<T>` | null/undefined 제거 | `NonNullable<string \| null>` |
| `ReturnType<T>` | 함수 반환 타입 추출 | `ReturnType<typeof fn>` |
| `Parameters<T>` | 함수 파라미터 타입 추출 | `Parameters<typeof fn>` |
| `Awaited<T>` | Promise unwrap | `Awaited<Promise<User>>` |

---

## Partial\<T\>

모든 프로퍼티를 optional로 만든다

```ts
// ✅ 업데이트 페이로드 — 일부만 바꿀 수 있음
function updateUser(id: string, data: Partial<User>) { ... }

// ✅ 테스트 픽스처
const mockUser: Partial<User> = { id: '123' };
```

**주의:** 중첩 객체는 shallow — 1단계만 optional

```ts
interface Config {
  db: { host: string; port: number };
}
type PartialConfig = Partial<Config>;
// db 자체는 optional이지만 db.host는 여전히 required
```

---

## Pick\<T, K\>

특정 프로퍼티만 골라낸다

```ts
// ✅ 응답에서 민감 정보 제외
type PublicUser = Pick<User, 'id' | 'name' | 'plan'>;

// ✅ JARVIS AI inference 클라이언트 — Message에서 일부만 전달
conversationHistory: Pick<Message, 'role' | 'content'>[];
```

---

## Omit\<T, K\>

특정 프로퍼티를 제외한다

```ts
// ✅ DB 자동 생성 필드 제외한 입력 타입
type CreateUserInput = Omit<User, 'id' | 'createdAt' | 'updatedAt'>;

// ✅ 비밀번호 제외
type SafeUser = Omit<User, 'passwordHash'>;
```

**Pick vs Omit 선택 기준:**
- 남길 게 적으면 `Pick` (2~3개)
- 제외할 게 적으면 `Omit` (1~2개)

---

## Record\<K, V\>

키-값 맵 타입

```ts
// ✅ 에러 코드 → 메시지 맵
const errorMessages: Record<string, string> = {
  AUTH_001: 'Invalid token',
  USER_001: 'User not found',
};

// ✅ 고정 키셋
type ProviderConfig = Record<'google' | 'apple' | 'kakao', OAuthConfig>;
```

---

## Extract\<T, U\> / Exclude\<T, U\>

```ts
type Role = 'admin' | 'user' | 'guest';

type PrivilegedRole = Extract<Role, 'admin' | 'user'>; // 'admin' | 'user'
type PublicRole = Exclude<Role, 'admin'>; // 'user' | 'guest'
```

---

## NonNullable\<T\>

`null`과 `undefined` 제거

```ts
// ✅ Prisma optional 필드 처리
type DefiniteTitle = NonNullable<Conversation['title']>; // string (null 제거)
```

---

## ReturnType\<T\> + Awaited\<T\>

```ts
async function generateTokenPair(userId: string): Promise<TokenPair> { ... }

type TokenPairResult = ReturnType<typeof generateTokenPair>; // Promise<TokenPair>
type TokenPairResolved = Awaited<ReturnType<typeof generateTokenPair>>; // TokenPair
```

---

## JARVIS AI 조합 패턴

```ts
// ✅ 생성 입력 — id/날짜 자동 생성 필드 제외
type CreateConversationInput = Omit<Conversation, 'id' | 'createdAt' | 'updatedAt' | 'status'>;

// ✅ 수정 입력 — 모두 optional
type UpdateUserInput = Partial<Pick<User, 'name' | 'timezone' | 'locale'>>;

// ✅ 안전한 응답 타입 — 내부 필드 제외
type SafeUserResponse = Omit<User, 'passwordHash' | 'deletedAt'>;

// ✅ inference client — Message 일부만 전달
Pick<Message, 'role' | 'content'>[]
```

---

## Gotcha

- `Partial<T>`는 shallow — 중첩 객체의 내부 프로퍼티는 여전히 required. `DeepPartial<T>`가 필요하면 직접 구현하거나 utility-types 라이브러리 사용
- `Omit<T, K>`에서 K에 없는 키를 지정해도 컴파일 에러가 나지 않음 — 조용히 무시됨. 오타 주의
- `ReturnType<typeof fn>` 패턴은 함수 시그니처가 바뀌면 자동으로 타입도 갱신 — 중복 선언 없이 최신 상태 유지

---

## 관련 개념

- [[interface-vs-type]] — 유틸리티 타입은 type으로
- [[generics]] — T에 제약 추가하는 패턴
- [[mapped-types]] — 유틸리티 타입 내부 동작 원리
- [[conditional-types]] — NonNullable, Extract, Exclude 내부 구현
