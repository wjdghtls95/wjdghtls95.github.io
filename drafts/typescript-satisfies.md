---
title: "TypeScript satisfies 연산자, 언제 쓰는가"
description: "as나 타입 선언 대신 satisfies를 써야 하는 이유"
date: "2026-07-27"
tags: ["learning", "TypeScript"]
---

## satisfies란

TypeScript 4.9에서 추가된 연산자다. 값이 특정 타입을 만족하는지 검사하면서도 타입을 좁히지 않는다.

```ts
type Color = "red" | "green" | "blue";

const palette = {
  red: [255, 0, 0],
  green: "#00ff00",
  blue: [0, 0, 255],
} satisfies Record<Color, string | number[]>;

palette.red.map(x => x); // ✅ 배열로 타입 추론됨
palette.green.toUpperCase(); // ✅ string으로 타입 추론됨
```

## as와의 차이

`as`는 타입을 강제로 덮어씌운다. 틀려도 오류가 안 난다.

```ts
const palette = {
  red: [255, 0, 0],
} as Record<Color, string | number[]>;

palette.red.map(x => x); // ❌ 컴파일 에러 — as로 단언하면 string | number[]로 넓혀져 배열 메서드 못 씀
```

`satisfies`는 검사만 하고 추론된 타입은 유지한다.

## 타입 선언과의 차이

```ts
// 타입 선언 — 모든 값이 string | number[]로 넓혀짐
const palette: Record<Color, string | number[]> = { ... };
palette.red // string | number[] → map 못 씀

// satisfies — 타입 검사 + 추론 유지
const palette = { ... } satisfies Record<Color, string | number[]>;
palette.red // number[] → map 가능
```

## 언제 쓰나

- 객체 리터럴이 특정 타입을 만족하는지 확인하고 싶을 때
- 근데 각 프로퍼티의 정확한 타입을 잃고 싶지 않을 때
- `as`로 타입 단언하는 곳을 대체할 때
