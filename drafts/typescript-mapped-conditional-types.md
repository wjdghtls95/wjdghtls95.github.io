---
title: "Mapped Types와 Conditional Types — 타입을 계산하다"
description: "TypeScript의 Mapped Types와 Conditional Types로 타입을 동적으로 변환하는 법. JARVIS Memory Tier 시스템 구현에서 실제로 쓰인 패턴."
date: "2026-08-11"
tags: ["TypeScript"]
draft: false
---

JARVIS Memory Tier 시스템을 설계할 때 문제가 하나 있었다

메모리 티어가 `CORE / SEARCHABLE / ARCHIVED` 세 가지인데, 각 티어마다 허용되는 작업이 달랐다 — `CORE`는 핀 고정, `SEARCHABLE`은 일반 검색, `ARCHIVED`는 읽기 전용. 이걸 런타임 조건문으로 막으면 누락이 생기고, API 레이어에서 타입으로 막으려니 중복 정의가 쌓였다

결국 선택한 건 Mapped Types와 Conditional Types의 조합이었다. 각 티어에 대해 허용 작업 타입을 계산하게 만들면, 잘못된 조합은 컴파일 타임에 걸린다

## 왜 이 기술이 필요한가

`User` 타입이 있고 업데이트 DTO를 만들어야 한다고 하면, 보통 이렇게 시작한다

```ts
interface UpdateUserDto {
  name?: string
  timezone?: string
  locale?: string
}
```

`User`가 바뀌면 `UpdateUserDto`도 따로 고쳐야 한다. 필드를 추가하면 DTO에 추가하고, 제거하면 DTO에서도 제거해야 한다. 동기화 실패는 조용한 버그로 이어진다

```ts
type UpdateUserDto = Partial<Pick<User, 'name' | 'timezone' | 'locale'>>
```

이 한 줄이 위 인터페이스와 동일하다. `User`가 바뀌면 타입 에러로 즉시 알 수 있다

Mapped Types와 Conditional Types는 이런 계산을 타입 레벨에서 수행한다

## Mapped Types — 어떻게 동작하나

### 기본 문법

```ts
{ [K in keyof T]: T[K] }
```

`keyof T`로 객체의 모든 키를 유니온으로 추출하고, 그 키를 순회하며 새 타입을 만든다

```ts
type Copy<T> = {
  [K in keyof T]: T[K]
}
// Copy<User> === User — 구조 그대로 복사
```

`Partial`, `Readonly`의 뼈대가 이것이다

### 수정자 — `?`와 `readonly`

`?`와 `readonly` 앞에 `-`를 붙이면 해당 수정자를 제거한다

```ts
type MyPartial<T>  = { [K in keyof T]?: T[K] }         // optional 추가
type MyRequired<T> = { [K in keyof T]-?: T[K] }        // optional 제거
type MyReadonly<T> = { readonly [K in keyof T]: T[K] }  // readonly 추가
type Mutable<T>    = { -readonly [K in keyof T]: T[K] } // readonly 제거
```

`-?`는 TypeScript 표준 라이브러리 `Required<T>` 내부에서 그대로 쓰이는 문법이다

### 키 재매핑 — `as` 절

TypeScript 4.1부터 `as` 절로 키 이름 자체를 변환할 수 있다

```ts
type Getters<T> = {
  [K in keyof T as `get${Capitalize<string & K>}`]: () => T[K]
}

interface User {
  id: string
  name: string
}

type UserGetters = Getters<User>
// { getId: () => string; getName: () => string }
```

`string & K`는 `K`가 `symbol`일 수 있어서 `Capitalize`에 넘기기 전에 string으로 좁히는 트릭이다

`as never`로 재매핑하면 해당 키를 결과 타입에서 제거한다 — 뒤에서 Conditional Types와 함께 필터링 패턴으로 이어진다

### 내장 유틸리티 타입의 구현

`Partial`, `Required`, `Readonly`, `Pick`, `Record`는 전부 Mapped Types로 구현되어 있다

```ts
type Partial<T>                 = { [K in keyof T]?: T[K] }
type Required<T>                = { [K in keyof T]-?: T[K] }
type Readonly<T>                = { readonly [K in keyof T]: T[K] }
type Pick<T, K extends keyof T> = { [P in K]: T[P] }
type Record<K extends keyof any, T> = { [P in K]: T }
```

`Omit`은 `Exclude`가 필요하다

```ts
type Omit<T, K extends keyof any> = Pick<T, Exclude<keyof T, K>>
```

`Exclude`는 Conditional Types다. 유틸리티 타입들이 서로 맞물려 있다

## Conditional Types — 어떻게 동작하나

### 기본 문법

```ts
T extends U ? X : Y
```

T가 U에 할당 가능하면 X, 아니면 Y

```ts
type IsString<T> = T extends string ? true : false

type A = IsString<string>    // true
type B = IsString<number>    // false
type C = IsString<'hello'>   // true — string literal은 string의 서브타입
```

### 분배 조건부 타입

유니온 타입에 Conditional Types를 적용하면 각 멤버에 자동으로 분배된다

```ts
type ToArray<T> = T extends unknown ? T[] : never

type A = ToArray<string | number>
// = ToArray<string> | ToArray<number>
// = string[] | number[]
```

분배를 막으려면 튜플로 감싼다

```ts
type NoDistribute<T> = [T] extends [unknown] ? T[] : never

type B = NoDistribute<string | number>  // (string | number)[]
```

### infer — 타입을 추출하다

`infer`는 조건부 타입 안에서 특정 위치의 타입을 캡처하는 키워드다

```ts
// Promise 내부 타입 추출
type Unwrap<T> = T extends Promise<infer U> ? U : T

type A = Unwrap<Promise<string>>  // string
type B = Unwrap<number>           // number

// 함수 반환 타입 추출 (ReturnType 내부 구현)
type MyReturnType<T> = T extends (...args: any[]) => infer R ? R : never

// 배열 요소 타입 추출
type ElementType<T> = T extends (infer U)[] ? U : never
type C = ElementType<User[]>  // User
```

`infer`는 `extends` 절 안에서만 쓸 수 있다

## 조합 — 둘을 같이 쓰면

### 타입 조건으로 키 필터링

Mapped Types의 `as` 절에 Conditional Types를 넣으면 특정 타입을 가진 키만 추출할 수 있다

```ts
type KeysOfType<T, U> = {
  [K in keyof T]: T[K] extends U ? K : never
}[keyof T]

interface User {
  id: string
  name: string
  age: number
  isActive: boolean
}

type StringKeys = KeysOfType<User, string>   // 'id' | 'name'
type BoolKeys   = KeysOfType<User, boolean>  // 'isActive'
```

`T[K] extends U ? K : never`로 조건을 만족하는 키는 키 이름을, 아닌 건 `never`로 만든다. 그리고 `[keyof T]`로 인덱싱하면 `never`는 유니온에서 자동으로 제거된다

### 서비스 반환 타입 재사용

```ts
// 서비스 메서드 반환 타입을 별도로 정의하지 않고 추론
type UserResult = Awaited<ReturnType<typeof UserService.prototype.updateUser>>
// → User

type AuthResult = Awaited<ReturnType<typeof AuthService.prototype.rotateRefreshToken>>
// → TokenPair
```

서비스 시그니처가 바뀌면 이 타입도 자동으로 따라간다

## JARVIS에서 실제로 쓴 예시

### Memory Tier enum과 허용 작업 매핑

JARVIS Memory 시스템에는 세 가지 티어가 있다

```ts
// Prisma schema에서 가져온 enum
type MemoryTier = 'CORE' | 'SEARCHABLE' | 'ARCHIVED'
```

각 티어에서 허용되는 작업이 다르다 — `CORE`는 핀 해제만, `SEARCHABLE`은 핀 고정 가능, `ARCHIVED`는 쓰기 불가. 이걸 Record + Conditional Types로 표현하면

```ts
type TierPermissions = Record<MemoryTier, {
  canPin: boolean
  canUpdate: boolean
  canDelete: boolean
}>

const TIER_PERMISSIONS: TierPermissions = {
  CORE:       { canPin: false, canUpdate: true,  canDelete: true  },
  SEARCHABLE: { canPin: true,  canUpdate: true,  canDelete: true  },
  ARCHIVED:   { canPin: false, canUpdate: false, canDelete: false },
}
```

`Record<MemoryTier, ...>`는 `MemoryTier`의 모든 멤버가 키로 존재해야 함을 강제한다. 새 티어를 추가하면 `TIER_PERMISSIONS`에도 추가하지 않으면 컴파일 에러가 난다

### 티어별 응답 타입 분기

`pinMemory`와 `unpinMemory`는 호출 후 반환 타입이 다르다 — 각각 `CORE`와 `SEARCHABLE`로 확정된 `Memory`를 반환한다. 이걸 타입으로 표현하면

```ts
type MemoryWithTier<T extends MemoryTier> = Omit<Memory, 'tier'> & { tier: T }

// pinMemory → tier가 'CORE'로 고정된 Memory
type PinnedMemory = MemoryWithTier<'CORE'>

// unpinMemory → tier가 'SEARCHABLE'로 고정된 Memory
type UnpinnedMemory = MemoryWithTier<'SEARCHABLE'>
```

서비스 코드에서는 실제로 이 패턴 대신 Prisma의 `Memory` 타입을 그대로 반환하지만, API 응답 DTO에서 tier를 좁혀야 할 때 이 방식이 유용하다

### 티어 기반 필드 필터링

`ARCHIVED` 메모리는 수정 불가 필드만 응답에 포함해야 한다면

```ts
type WritableMemoryFields = KeysOfType<Memory, string | number>  // 수정 가능한 필드만
type ArchivedMemoryResponse = Readonly<Pick<Memory, 'id' | 'content' | 'createdAt' | 'tier'>>
```

Mapped Types의 `readonly` 수정자로 `ARCHIVED` 응답 타입 자체가 수정 불가임을 타입에서 보장한다

### 실제 서비스 코드에서의 패턴

`memory.service.ts`에서 `pinMemory`는 트랜잭션 안에서 `CORE` 티어 한도(10개)를 검사한다

```ts
async pinMemory(userId: string, id: string): Promise<Memory> {
  const before = await this.memoryRepository.findOneByUserIdAndId(userId, id)

  if (!before) throw new DomainException(DOMAIN_ERRORS.MEMORY_NOT_FOUND)

  // 이미 CORE면 early return — 불필요한 트랜잭션 없음
  if (before.tier === 'CORE') return before

  const updated = await this.pinMemoryInTx(userId, id)

  // Qdrant sync는 best-effort — 실패해도 DB 상태가 정답
  await this.warnService.guard(
    this.inferenceClient.updateMemoryTier(id, 'CORE'),
    SERVICE_WARN_ERRORS.MEMORY_TIER_SYNC_FAILED,
  )

  return updated
}
```

`tier === 'CORE'` 비교가 타입 안전하게 동작하는 건 Prisma가 생성한 `Memory` 타입에 `tier: MemoryTier`가 있기 때문이다. 문자열 리터럴 오타는 컴파일 타임에 잡힌다

## 함정 (Gotchas)

**`keyof`는 컴파일 타임 전용**

`Object.keys(obj)`는 런타임에서 `string[]`을 반환한다. `keyof T`는 컴파일 타임 유니온 리터럴 타입이고 런타임에는 존재하지 않는다. 이 둘을 혼동하면 런타임에 `for (const key of Object.keys(obj))`에서 타입 에러 없이 잘못된 값이 들어올 수 있다

**동형 vs 비동형 Mapped Types**

`keyof T` 기반으로 순회하는 동형(Homomorphic) Mapped Types는 원본의 `readonly`, `optional` 수정자를 유지한다. 임의 키 유니온을 순회하는 비동형은 수정자를 갖지 않는다

```ts
// 동형 — User의 readonly 필드가 있으면 유지됨
type MyPartial<T> = { [K in keyof T]?: T[K] }

// 비동형 — 새 타입 생성, 원본 수정자 없음
type MyRecord<K extends string, V> = { [P in K]: V }
```

**분배가 일어나는 조건**

분배는 제네릭 타입 파라미터에 유니온이 들어올 때만 일어난다. `T`가 `never`이면 결과도 `never`가 된다. 의도치 않게 분배를 막으려면 `[T] extends [U]` 튜플 트릭을 쓴다

**재귀 Conditional Types의 깊이 제한**

`Awaited<T>` 처럼 재귀적으로 자신을 호출하는 Conditional Types는 TypeScript 컴파일러에서 약 100레벨 깊이 제한이 있다. 실제로 `Promise<Promise<Promise<...>>>` 수준의 중첩은 거의 없어서 문제가 되는 경우는 드물다

**과도한 중첩**

3단계 이상 중첩은 읽기 어렵다

```ts
// ❌ 3단계 — 설명 없이 읽기 어려움
type T = Readonly<Partial<Pick<Omit<User, 'id'>, 'name' | 'timezone'>>>

// ✅ 중간 타입으로 쪼개기
type EditableFields = Pick<Omit<User, 'id'>, 'name' | 'timezone'>
type UpdateUserDto  = Partial<EditableFields>
```

조합 깊이가 2단계를 넘으면 중간 타입으로 이름을 붙이는 게 낫다
