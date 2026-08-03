---
title: "TypeScript enum vs as const, 언제 뭘 쓰는가"
description: "TypeScript에서 enum과 as const의 차이를 알아보고 각각 언제 사용해야 하는지 정리합니다."
date: "2026-07-27"
tags: ["learning", "TypeScript"]
---

## enum이란

TypeScript의 `enum`은 명명된 상수 집합을 정의하는 방법입니다.

```typescript
enum Direction {
  Up = "UP",
  Down = "DOWN",
  Left = "LEFT",
  Right = "RIGHT",
}
```

enum은 TypeScript 고유 기능으로, 컴파일 시 JavaScript 객체로 변환됩니다.

## as const란

`as const`는 TypeScript에서 객체나 배열을 readonly로 만들고 타입을 리터럴로 좁히는 방법입니다.

```typescript
const Direction = {
  Up: "UP",
  Down: "DOWN",
  Left: "LEFT",
  Right: "RIGHT",
} as const;

type Direction = typeof Direction[keyof typeof Direction];
```

## 차이점

| | enum | as const |
|--|------|----------|
| 런타임 존재 | ✅ JS 객체로 변환 | ✅ 일반 객체 |
| 타입 좁힘 | ✅ | ✅ |
| 트리쉐이킹 | ❌ 번들에 포함 | ✅ 사용 안 하면 제거 |
| 역방향 매핑 | ✅ (숫자 enum만) | ❌ |

## 언제 뭘 쓰나

**enum 쓸 때:**
- 역방향 매핑이 필요할 때
- 외부 라이브러리와 호환성이 중요할 때

**as const 쓸 때:**
- 번들 크기를 최적화하고 싶을 때
- 순수 TypeScript 타입 안전성만 필요할 때
- 대부분의 경우 as const가 더 권장됨
