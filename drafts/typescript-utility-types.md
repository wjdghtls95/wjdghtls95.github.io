---
title: "TypeScript 유틸리티 타입 실전 (Partial, Pick, Omit, Required)"
description: "자주 쓰는 유틸리티 타입 10가지와 조합 패턴, 놓치기 쉬운 함정을 코드 중심으로 정리"
date: "2026-07-28"
tags: ["learning"]
study: "학습/TypeScript/utility-types.md"
rewritten: true
---

`UpdateUserDto`를 만들 때 `User` 타입 프로퍼티를 일일이 복사하고, `User`가 바뀌면 DTO도 따로 수정하고 있다면 — 유틸리티 타입을 아직 안 쓰는 거다.

유틸리티 타입은 기존 타입을 변환해 새 타입을 만드는 내장 제네릭이다. 내부적으로 Mapped Types와 Conditional Types로 구현되어 있고, 별도 설치 없이 바로 쓸 수 있다.

## 한눈에 보기

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

## Partial\<T\> / Required\<T\> / Readonly\<T\>

`Partial`은 모든 프로퍼티를 optional로, `Required`는 전부 required로, `Readonly`는 전부 readonly로 만든다.

```ts
// ✅ 업데이트 페이로드 — 일부만 보낼 수 있음
function updateUser(id: string, data: Partial<User>) { ... }

// ✅ 테스트 픽스처 — 필요한 필드만 채움
const mockUser: Partial<User> = { id: '123' };

// ✅ optional이 있는 프로파일 타입에서 모두 채워진 버전 강제
type CompleteProfile = Required<UserProfile>;

// ✅ 설정 객체를 변경 불가로
const DB_CONFIG: Readonly<DbConfig> = {
  host: 'localhost',
  port: 5432,
};
```

`Partial`은 **shallow** — 1단계만 optional로 만들고 중첩 객체 내부는 건드리지 않는다.

```ts
interface Config {
  db: { host: string; port: number };
}
type PartialConfig = Partial<Config>;
// db 자체는 optional이지만 db.host는 여전히 required
```

중첩까지 optional이 필요하면 `DeepPartial<T>`를 직접 구현하거나 `utility-types` 라이브러리를 쓴다.

## Pick\<T, K\> / Omit\<T, K\>

`Pick`은 필요한 것만 골라내고, `Omit`은 빼고 싶은 것만 제거한다.

어느 쪽을 쓸지 기준은 간단하다 — 남길 게 적으면 `Pick`, 제외할 게 적으면 `Omit`.

```ts
// ✅ Pick — 응답에서 필요한 필드만
type PublicUser = Pick<User, 'id' | 'name' | 'plan'>;

// inference client에 Message 일부만 전달
conversationHistory: Pick<Message, 'role' | 'content'>[];

// ✅ Omit — 자동 생성 필드 제외한 입력 타입
type CreateUserInput = Omit<User, 'id' | 'createdAt' | 'updatedAt'>;

// ✅ Omit — 민감 정보 제외
type SafeUser = Omit<User, 'passwordHash'>;
```

`Omit`에서 존재하지 않는 키를 지정해도 컴파일 에러가 나지 않는다. 오타가 있어도 조용히 무시된다.

```ts
// ❌ 오타가 있어도 에러 없음
type Wrong = Omit<User, 'passworHash'>; // 'passwordHash' 오타 — 그냥 통과
```

## Record\<K, V\>

키-값 맵 타입이다. `{ [key: string]: V }` 대신 `Record`를 쓰면 키 타입을 더 정밀하게 제어할 수 있다.

```ts
// ✅ 에러 코드 → 메시지 맵
const errorMessages: Record<string, string> = {
  AUTH_001: 'Invalid token',
  USER_001: 'User not found',
};

// ✅ 고정 키셋 — 키를 추가하거나 빠뜨리면 에러
type ProviderConfig = Record<'google' | 'apple' | 'kakao', OAuthConfig>;
```

## Extract\<T, U\> / Exclude\<T, U\>

유니온 타입을 필터링할 때 쓴다. `Extract`는 교집합, `Exclude`는 차집합이다.

```ts
type Role = 'admin' | 'user' | 'guest';

type PrivilegedRole = Extract<Role, 'admin' | 'user'>; // 'admin' | 'user'
type PublicRole = Exclude<Role, 'admin'>; // 'user' | 'guest'
```

## NonNullable\<T\>

`null`과 `undefined`를 모두 제거한다. Prisma처럼 optional 필드가 많은 스키마에서 자주 쓴다.

```ts
// ✅ Prisma optional 필드 처리
type DefiniteTitle = NonNullable<Conversation['title']>; // string (null 제거)
```

## ReturnType\<T\> / Parameters\<T\> + Awaited\<T\>

함수 반환 타입이나 파라미터 타입을 별도로 선언하지 않아도 된다. 함수 시그니처가 바뀌면 타입도 자동으로 갱신된다.

```ts
async function generateTokenPair(userId: string): Promise<TokenPair> { ... }

type TokenPairResult = ReturnType<typeof generateTokenPair>;            // Promise<TokenPair>
type TokenPairResolved = Awaited<ReturnType<typeof generateTokenPair>>; // TokenPair

// ✅ 파라미터 타입 추출 — 함수 시그니처와 동기화 유지
type GenerateTokenParams = Parameters<typeof generateTokenPair>; // [userId: string]
```

`Awaited`는 `Promise`를 재귀적으로 unwrap한다. `Promise<Promise<User>>` 같은 중첩 케이스도 `User`까지 풀어낸다.

## 조합 패턴

유틸리티 타입은 중첩해서 쓸 때 더 강력해진다.

```ts
// ✅ 생성 입력 — 자동 생성 필드 제외
type CreateConversationInput = Omit<Conversation, 'id' | 'createdAt' | 'updatedAt' | 'status'>;

// ✅ 수정 입력 — 수정 가능한 필드 명시 + 전부 optional
type UpdateUserInput = Partial<Pick<User, 'name' | 'timezone' | 'locale'>>;

// ✅ 안전한 응답 타입 — 내부 필드 제외
type SafeUserResponse = Omit<User, 'passwordHash' | 'deletedAt'>;
```

`Partial<Pick<User, 'name' | 'timezone' | 'locale'>>` 패턴이 특히 유용하다. 수정 가능한 필드를 명시적으로 제한하면서, 그 중 어떤 것을 보낼지는 자유롭게 선택할 수 있다.
