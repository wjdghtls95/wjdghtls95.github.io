---
title: "TypeScript enum vs as const, 언제 뭘 쓰는가"
description: "enum과 as const는 겉으로 비슷해 보이지만 컴파일 결과가 다르다. 번들 크기, 역방향 매핑, const enum까지 실제 차이를 짚는다."
date: "2026-07-27"
tags: ["learning", "TypeScript"]
rewritten: true
---

같은 상수 집합을 enum으로 쓸 수도 있고, as const로 쓸 수도 있다. 둘 다 타입 안전성을 주는데, 왜 선택을 고민해야 할까? 컴파일 결과를 보면 답이 나온다.

## enum의 컴파일 결과

TypeScript에서 enum을 쓰면 런타임에 실제 JavaScript 객체가 생긴다.

```typescript
enum Direction {
  Up = "UP",
  Down = "DOWN",
}
```

컴파일 후:

```javascript
var Direction;
(function (Direction) {
  Direction["Up"] = "UP";
  Direction["Down"] = "DOWN";
})(Direction || (Direction = {}));
```

즉, enum은 타입이 아니라 값이다. 번들에 무조건 포함된다.

## as const의 컴파일 결과

```typescript
const Direction = {
  Up: "UP",
  Down: "DOWN",
} as const;
```

컴파일 후:

```javascript
const Direction = {
  Up: "UP",
  Down: "DOWN",
};
```

`as const`는 TypeScript 전용 키워드다. 런타임엔 평범한 객체고, 사용하지 않으면 번들러가 제거한다.

## 타입 추출

as const로 만든 객체에서 유니온 타입을 뽑으려면 한 줄이 필요하다.

```typescript
const Direction = {
  Up: "UP",
  Down: "DOWN",
} as const;

type DirectionValue = typeof Direction[keyof typeof Direction];
// "UP" | "DOWN"
```

익숙해지면 자연스럽지만, 처음엔 `typeof Direction[keyof typeof Direction]`이 낯설다. enum은 타입 이름 자체가 유니온 역할을 해서 별도 추출이 필요 없다.

## 숫자 enum의 역방향 매핑

숫자 enum에는 특수한 동작이 있다.

```typescript
enum Status {
  Active,   // 0
  Inactive, // 1
}

console.log(Status[0]); // "Active"
```

값으로 이름을 역조회할 수 있다. 컴파일 결과를 보면 이유가 명확하다.

```javascript
var Status;
(function (Status) {
  Status[Status["Active"] = 0] = "Active";
  Status[Status["Inactive"] = 1] = "Inactive";
})(Status || (Status = {}));
```

양방향 매핑이라 번들 크기가 두 배가 된다. 문자열 enum은 역방향 매핑이 없다.

## const enum — 런타임 비용이 없지만

`const enum`이라는 변형도 있다. 컴파일 타임에 값을 직접 인라이닝하고 런타임 객체를 생성하지 않는다.

```typescript
const enum Direction {
  Up = "UP",
  Down = "DOWN",
}

const d = Direction.Up;
```

컴파일 후:

```javascript
const d = "UP"; // enum 객체 자체는 사라짐
```

런타임 비용이 없어서 좋아 보이지만, 외부 라이브러리에서 쓰거나 babel/esbuild로 트랜스파일할 때 문제가 생긴다. `isolatedModules` 옵션과 호환되지 않아서 현실적으로 쓰기 어렵다.

## 실제로 뭘 쓸 것인가

대부분의 경우 `as const`가 낫다.

```typescript
// ❌ 이 정도 상황에서 enum은 번들 비용이 아깝다
enum Theme {
  Light = "light",
  Dark = "dark",
}

// ✅ 같은 타입 안전성, 더 가벼운 번들
const Theme = {
  Light: "light",
  Dark: "dark",
} as const;

type Theme = typeof Theme[keyof typeof Theme];
```

enum을 선택하는 상황은 구체적이다:
- 숫자 enum의 역방향 매핑이 실제로 필요한 레거시 코드
- enum 타입을 요구하는 외부 라이브러리와 연동

그 외에는 as const + 타입 추출로 충분하다.
