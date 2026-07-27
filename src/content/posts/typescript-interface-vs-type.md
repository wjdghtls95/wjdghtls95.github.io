---
title: "TypeScript interface vs type, 언제 뭘 쓰는가"
description: "TypeScript에서 interface와 type을 어떤 상황에서 써야 하는지 실제 코드 예시로 정리합니다"
pubDatetime: 2026-07-23T00:00:00Z
tags: ["TypeScript", "개발", "백엔드"]
featured: false
---

TypeScript를 처음 쓰다 보면 `interface`로도 객체 구조를 정의할 수 있고, `type`으로도 할 수 있다. 둘 다 컴파일되고 에러도 안 난다. 그래서 팀마다 쓰는 방식이 달라지고, 코드베이스 안에서도 뒤섞인다

## 둘이 뭔가

`interface`는 객체의 형태(shape)를 선언하는 TypeScript 전용 문법이다. 컴파일 후 JS에는 남지 않는다

```ts
interface User {
  id: string
  email: string
}
```

`type`은 타입에 이름(alias)을 붙이는 문법이다. 객체뿐 아니라 유니온, 함수, 튜플 등 어떤 타입이든 이름을 붙일 수 있다

```ts
type Status = 'active' | 'inactive'
type GetUser = (id: string) => Promise<User>
```

둘이 헷갈리는 이유는 객체 구조를 정의할 때 둘 다 가능하기 때문이다

```ts
interface User { id: string; email: string }
type User = { id: string; email: string }   // 둘 다 동작
```

## interface를 써야 하는 경우

객체 구조를 정의할 때 기본값은 `interface`다

확장이 필요할 때 `extends`를 쓸 수 있다. `type`도 교차 타입(`&`)으로 같은 구조를 만들 수 있지만, `extends`가 확장 관계를 더 명시적으로 표현한다:

```ts
// interface extends — 확장 관계가 명확
interface AdminUser extends User {
  permissions: string[]
}

// type & — 같은 구조지만 확장 관계가 덜 명시적
type AdminUser = User & { permissions: string[] }
```

`interface`만 할 수 있는 게 있다. 선언 병합(Declaration Merging)이다. 같은 이름으로 두 번 선언하면 자동으로 합쳐진다. 라이브러리 타입을 확장할 때 쓴다:

```ts
// Express Request에 user 프로퍼티 추가
declare global {
  namespace Express {
    interface Request {
      user?: User
    }
  }
}
```

`type`으로는 이게 불가능하다

## type을 써야 하는 경우

`interface` 문법으로 표현이 안 되는 경우에 쓴다

유니온 타입:

```ts
type Status = 'active' | 'inactive' | 'archived'
type HttpMethod = 'GET' | 'POST' | 'PUT' | 'DELETE'
```

유틸리티 타입 조합:

```ts
type CreateUserInput = Omit<User, 'id' | 'createdAt' | 'updatedAt'>
type UpdateProfileInput = Partial<Pick<User, 'name' | 'timezone'>>
```

함수 타입과 튜플:

```ts
type EventHandler = (event: MouseEvent) => void
type Coordinate = [number, number]
```

Mapped type과 Conditional type — 객체 형태임에도 `type`만 가능하다:

```ts
type Keys = 'a' | 'b'
type Mapped = { [K in Keys]: string }            // interface로 불가

type IsString<T> = T extends string ? true : false  // interface로 불가
```

## 결정 플로우

```
interface 문법으로 표현 가능?
  ├─ Yes → interface (객체 구조, extends 확장)
  └─ No  → type
           (유니온 / 유틸리티 조합 / 함수 타입 / 튜플 /
            mapped type / conditional type)
```

## 실제 코드에서

실제 NestJS 프로젝트 기준으로 `interfaces/` 폴더에는 `interface`로 정의한 순수 타입만 넣는다. 서비스 파일 안에 `interface`를 정의하면 나중에 재사용도 어렵고 찾기도 힘들다

예시: [`token-pair.interface.ts`](https://github.com/wjdghtls95/nestjs-boilerplate/blob/830ea9a/src/auth/interfaces/token-pair.interface.ts)

## 알아두면 좋은 것

TypeScript는 구조적 타이핑(Structural Typing)이다. `interface`와 `type` 모두 같은 구조면 서로 호환된다

선언 병합은 양날의 검이다. 라이브러리 타입 확장에 유리하지만, 의도치 않게 같은 이름의 `interface`가 두 곳에 선언되면 자동으로 합쳐진다. 이게 싫다면 `type`을 쓰면 중복 선언 자체가 에러가 된다

---

`enum`과 `as const`도 타입 정의와 함께 자주 혼동되는데, 이건 다음 포스트에서 다룬다
