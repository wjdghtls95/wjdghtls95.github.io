---
title: "Mapped Types와 Conditional Types: 타입을 계산하다"
description: "TypeScript Mapped Types와 Conditional Types 기본 문법부터 infer, 분배 조건부 타입, 실전 패턴까지 정리"
pubDate: 2026-08-11
category: "TypeScript"
tags: ["TypeScript", "개발", "백엔드"]
series: "TypeScript 타입 시스템 완전 정복"
source: "TypeScript/mapped-types.md + TypeScript/conditional-types.md"
---

TypeScript 타입 시스템에는 타입을 *변환*하는 두 가지 도구가 있다

Mapped Types는 객체 타입의 구조를 순회하며 새 타입을 만들고, Conditional Types는 타입 조건에 따라 분기한다

이 둘을 조합하면 `Partial`, `Pick`, `ReturnType` 같은 내장 유틸리티 타입을 직접 구현할 수 있게 된다

## Mapped Types: 타입을 순회하다

### 기본 문법

```ts
{ [K in keyof T]: T[K] }
```

`keyof T`로 객체의 모든 키를 유니온으로 추출한 뒤, 그 키를 하나씩 순회하며 새 타입을 만든다

```ts
type Copy<T> = {
  [K in keyof T]: T[K]
}
// Copy<User> === User
```

가장 단순한 예시지만 이게 `Partial`, `Readonly`의 뼈대다

### 수정자: -? 와 -readonly

`?`와 `readonly` 앞에 `-`를 붙이면 제거한다

```ts
type MyPartial<T>  = { [K in keyof T]?: T[K] }        // optional 추가
type MyRequired<T> = { [K in keyof T]-?: T[K] }       // optional 제거
type MyReadonly<T> = { readonly [K in keyof T]: T[K] } // readonly 추가
type Mutable<T>    = { -readonly [K in keyof T]: T[K] } // readonly 제거
```

`-?`는 TypeScript 표준 라이브러리 `Required<T>` 내부에서 그대로 쓰이는 문법이다

### 키 재매핑: as 절

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

`string & K`는 `K`가 `symbol`일 수도 있어서 `Capitalize`에 넘기기 전에 string으로 좁히는 트릭이다

`as never`로 재매핑하면 해당 키를 타입에서 제거할 수 있다. 뒤에서 Conditional Types와 함께 필터링 패턴으로 이어진다

### 내장 유틸리티 타입의 구현

`Partial`, `Required`, `Readonly`, `Pick`, `Record`는 전부 Mapped Types로 구현되어 있다

```ts
type Partial<T>  = { [K in keyof T]?: T[K] }
type Required<T> = { [K in keyof T]-?: T[K] }
type Readonly<T> = { readonly [K in keyof T]: T[K] }
type Pick<T, K extends keyof T> = { [P in K]: T[P] }
type Record<K extends keyof any, T> = { [P in K]: T }
```

`Omit`은 `Exclude`가 필요하다

```ts
type Omit<T, K extends keyof any> = Pick<T, Exclude<keyof T, K>>
```

`Exclude`는 Conditional Types다. 유틸리티 타입들이 서로 맞물려 있다

### 실전: 응답 타입 가공

```ts
// Prisma 엔티티에서 민감 필드를 제외한 응답 타입
type SafeUser = Omit<User, 'passwordHash' | 'deletedAt'>

// 각 필드에 validator 함수를 매핑
type ValidationSchema<T> = {
  [K in keyof T]: (value: T[K]) => boolean
}

const userSchema: ValidationSchema<User> = {
  id:    (v) => v.length > 0,
  email: (v) => v.includes('@'),
  name:  (v) => v.length >= 2,
}
```

---

## Conditional Types: 타입을 분기하다

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

### infer: 타입을 추출하다

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

### 내장 조건부 유틸리티 타입

```ts
type NonNullable<T> = T extends null | undefined ? never : T

type Extract<T, U> = T extends U ? T : never     // 겹치는 것만 남김
type Exclude<T, U> = T extends U ? never : T     // 제외

type ReturnType<T extends (...args: any) => any> =
  T extends (...args: any) => infer R ? R : any
```

`Awaited`는 Promise를 재귀적으로 unwrap한다

```ts
type Awaited<T> =
  T extends null | undefined ? T :
    T extends object & { then(onfulfilled: infer F, ...args: any): any }
      ? F extends ((value: infer V, ...args: any) => any)
        ? Awaited<V>
        : never
      : T
```

재귀 Conditional Types는 TypeScript 컴파일러에서 깊이 제한(약 100레벨)이 있다

---

## 두 개를 조합하면

### 타입 조건으로 키 필터링

Mapped Types의 `as` 절에 Conditional Types를 넣으면 특정 조건을 만족하는 키만 추출할 수 있다

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

`T[K] extends U ? K : never`로 조건을 만족하는 키는 키 이름을, 아닌 건 `never`로 만들고 `[keyof T]`로 인덱싱하면 `never`는 유니온에서 자동으로 제거된다

### 서비스 반환 타입 재사용

```ts
type UserResult = Awaited<ReturnType<typeof UserService.prototype.updateUser>>
// → User

type AuthResult = Awaited<ReturnType<typeof AuthService.prototype.rotateRefreshToken>>
// → TokenPair
```

서비스 시그니처가 바뀌면 이 타입도 자동으로 따라간다. 타입을 중복 정의할 필요가 없다

---

## Gotcha

**keyof는 컴파일 타임 전용**

`Object.keys(obj)`는 런타임에서 `string[]`을 반환한다. `keyof T`는 컴파일 타임 유니온 리터럴 타입이고 런타임에 존재하지 않는다

**동형 vs 비동형 Mapped Types**

`keyof T` 기반으로 순회하는 동형(Homomorphic) Mapped Types는 원본의 `readonly`, `optional` 수정자를 유지한다. 임의 키 유니온을 순회하는 비동형은 수정자를 갖지 않는다

```ts
// 동형 — User의 readonly 필드가 있으면 유지됨
type MyPartial<T> = { [K in keyof T]?: T[K] }

// 비동형 — 새 타입 생성, 원본 수정자 없음
type MyRecord<K extends string, V> = { [P in K]: V }
```

**분배가 일어나는 조건**

분배는 제네릭 타입 파라미터에 유니온이 들어올 때만 일어난다. `T`가 `never`이면 결과도 `never`가 된다. 분배를 막으려면 `[T] extends [U]` 튜플 트릭을 쓴다

**`as never` 필터링**

`as` 절에서 `never`로 재매핑하면 해당 키가 결과 타입에서 제거된다. `KeysOfType` 같은 필터링 패턴의 핵심이다
