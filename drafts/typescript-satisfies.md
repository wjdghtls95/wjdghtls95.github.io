---
title: "TypeScript satisfies 연산자, 언제 쓰는가"
description: "타입 검사는 하되 추론된 타입을 그대로 유지하고 싶을 때 satisfies가 정확히 그 역할을 한다."
date: "2026-07-27"
tags: ["learning", "TypeScript"]
rewritten: true
---

객체에 타입을 붙이는 방법은 크게 두 가지다. 타입 선언(`: Type`)이나 단언(`as Type`). 둘 다 쓰다 보면 어느 순간 "분명히 배열인데 왜 `.map()`을 못 쓰지?"라는 상황을 만난다.

## 타입 선언이 추론을 덮어쓴다

```ts
type Color = "red" | "green" | "blue";

const palette: Record<Color, string | number[]> = {
  red: [255, 0, 0],
  green: "#00ff00",
  blue: [0, 0, 255],
};

palette.red.map(x => x);     // ❌ string | number[] 타입이라 배열 메서드 못 씀
palette.green.toUpperCase(); // ❌ 같은 이유
```

`red`가 실제로 `number[]`인데도 타입 선언이 `string | number[]`로 넓혀버린다. 타입 검사는 통과했지만 추론 정보는 사라졌다.

## as는 검사도 안 한다

`as`는 더 심하다. 검사 자체를 건너뛴다.

```ts
// ❌ green, blue 키가 없는데도 컴파일 오류 없음
const wrong = {
  red: [255, 0, 0],
} as Record<Color, string | number[]>;

// ❌ as로 단언하면 string | number[]로 넓혀져 배열 메서드 못 씀
const palette = {
  red: [255, 0, 0],
  green: "#00ff00",
  blue: [0, 0, 255],
} as Record<Color, string | number[]>;

palette.red.map(x => x); // ❌ Property 'map' does not exist on type 'string | number[]'
```

타입이 맞지 않아도 컴파일러가 그냥 믿어준다. "내가 더 잘 알아"라고 강요하는 것에 가깝다.

## satisfies — 검사하고, 추론은 유지

TypeScript 4.9에서 추가된 `satisfies` 연산자는 두 가지를 동시에 한다.

```ts
const palette = {
  red: [255, 0, 0],
  green: "#00ff00",
  blue: [0, 0, 255],
} satisfies Record<Color, string | number[]>;

palette.red.map(x => x);     // ✅ number[]로 추론됨
palette.green.toUpperCase(); // ✅ string으로 추론됨
```

- `Record<Color, string | number[]>` 조건을 만족하는지 **검사**한다 (없는 키가 있으면 오류)
- 각 프로퍼티는 실제 타입(`number[]`, `string`)으로 추론된 상태를 **유지**한다

## 세 방식 비교

| | 타입 검사 | 추론 유지 |
|---|---|---|
| `: Record<...>` | ✅ | ❌ (넓혀짐) |
| `as Record<...>` | ❌ | ❌ |
| `satisfies Record<...>` | ✅ | ✅ |

## 실제로 쓰는 경우

config 객체나 테마처럼 값마다 타입이 다른 구조에서 특히 유용하다.

```ts
type ThemeKey = "primary" | "secondary" | "danger";

const theme = {
  primary: { hex: "#007bff", rgb: [0, 123, 255] },
  secondary: { hex: "#6c757d", rgb: [108, 117, 125] },
  danger: { hex: "#dc3545", rgb: [220, 53, 69] },
} satisfies Record<ThemeKey, { hex: string; rgb: number[] }>;

theme.primary.rgb.length;         // ✅ number[]로 추론됨
theme.danger.hex.startsWith("#"); // ✅ string으로 추론됨
```

`as`를 쓰고 싶은 상황이라면 대부분 `satisfies`로 대체할 수 있다. 타입 안전성도 챙기고, 각 값의 구체적인 타입도 그대로 쓸 수 있다.
