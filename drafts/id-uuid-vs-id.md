---
title: "UUID vs 순차 ID, DB 기본키를 어떻게 선택해야 하나"
description: "INT, UUID v4, UUID v7, ULID, Snowflake를 B-tree 인덱스와 보안 관점에서 비교하고 선택 기준을 정리"
date: "2026-10-07"
tags: ["데이터베이스"]
qa_done: true
rewritten: true
---

기본키 선택은 한번 정하면 바꾸기 어렵다
FK, 인덱스, 외부 API, JWT 페이로드까지 ID가 퍼지기 때문이다

선택 기준은 딱 두 가지로 줄어든다
**ID가 밖으로 노출되는가**, 그리고 **삽입 패턴이 B-tree 인덱스에 어떤 영향을 주는가**

## 종류 한눈에 보기

| 종류 | 예시 | 크기 | 정렬 | 생성 위치 |
|---|---|---|---|---|
| INT (AUTO_INCREMENT) | `12345` | 4 bytes | ✅ | DB만 |
| BIGINT | `9187654321` | 8 bytes | ✅ | DB만 |
| UUID v4 | `97d107d8-d198-4b1a-9b0a-7ca88f485efe` | 16 bytes | ❌ 랜덤 | 어디서나 |
| UUID v7 | `018f1a2b-3c4d-7e5f-8a9b-0c1d2e3f4a5b` | 16 bytes | ✅ 시간순 | 어디서나 |
| ULID | `01ARZ3NDEKTSV4RRFFQ69G5FAV` | 16 bytes | ✅ 시간순 | 어디서나 |
| Snowflake ID | `1541815603606036480` | 8 bytes | ✅ 시간순 | 서버당 고유 |

## 순차 ID (INT / BIGINT)

PostgreSQL의 `SERIAL`은 `INT` + sequence, `BIGSERIAL`은 `BIGINT` + sequence
MySQL은 `AUTO_INCREMENT`로 같은 일을 한다
최대값은 INT가 약 21억(`2^31 - 1`), BIGINT가 약 920경(`2^63 - 1`)

가장 작은 키라서 인덱스 효율이 좋다
새 행은 항상 B-tree 오른쪽 끝에 붙기 때문에 페이지 분할이 거의 없다

```sql
-- ✅ 작은 키, 오른쪽 끝에만 삽입, FK JOIN도 가볍다
SELECT * FROM users WHERE id = 12345;
```

문제는 밖으로 노출될 때다

```
GET /api/users/1
GET /api/users/2   ← 다음 ID가 그냥 예측된다
GET /api/users/3   ← 권한 검사가 빠져 있으면 IDOR 공격으로 이어진다
```

ID 값만 봐도 가입 순서나 전체 유저 규모를 짐작할 수 있다
또 DB 한 곳에서만 만들 수 있어서 샤딩이나 멀티 마스터 환경에서는 충돌 위험이 생긴다

그래서 외부 API로 직접 노출되지 않는 내부 시스템, 단일 DB 인스턴스, 조회 성능이 중요한 환경에 맞다

## UUID v4, 완전 랜덤

128비트 중 122비트가 랜덤이다 (RFC 4122, 이후 RFC 9562로 대체)
PostgreSQL 13+는 `gen_random_uuid()`를 내장하고 있어서 별도 확장 없이 쓸 수 있다

장점은 분명하다

- 서버, DB, 서비스가 달라도 충돌하지 않는다
- 애플리케이션에서 만들 수 있어서 DB 왕복 없이 ID를 미리 알 수 있다
- 예측이 안 된다

단점은 인덱스에서 나온다

```sql
-- ❌ 랜덤 값이라 B-tree의 아무 위치에나 들어간다
INSERT INTO users (id) VALUES ('97d107d8-...');
INSERT INTO users (id) VALUES ('12ab34cd-...');
-- 페이지 분할이 잦아지고 디스크 쓰기와 인덱스 파편화가 늘어난다
```

```
순차 ID 삽입:
[1][2][3][4][5]   ← 항상 오른쪽 끝에 추가

UUID v4 삽입:
[a3][b7][c1]
      ↑
   랜덤 위치에 끼어들면서 기존 페이지를 쪼개고 재배치
```

크기도 INT의 4배라서 인덱스와 FK까지 합치면 영향이 커진다
시간순 정렬이 안 되니까 페이지네이션은 cursor 방식으로 풀 수 없다는 점도 같이 따라온다

UUID v1은 MAC 주소와 타임스탬프가 들어가서 서버 정보가 노출될 수 있다
웹 서비스에서는 v4나 v7을 쓴다

## UUID v7, 시간순 정렬이 되는 UUID

RFC 9562(2024)에서 v6, v7, v8이 새로 정의됐다
v7은 앞 48비트가 밀리초 단위 Unix 타임스탬프고 나머지가 랜덤이다

```
┌──────────────────────────────────────────────────────┐
│ 48bits: timestamp (ms) │ 4bits: ver │ 76bits: random │
└──────────────────────────────────────────────────────┘
018f1a2b-3c4d-7e5f-8a9b-0c1d2e3f4a5b
├── 018f1a2b3c4d: 타임스탬프라서 정렬 가능
└── 7: UUID 버전 7
```

v4와 비교하면 이렇다

- 값이 시간에 따라 거의 단조증가해서 B-tree 페이지 분할이 줄어든다
- `ORDER BY id`가 곧 생성 시간순이라 cursor 페이지네이션에 쓸 수 있다
- 타임스탬프 부분은 드러나지만 나머지가 랜덤이라 순차 ID처럼 쉽게 추측되지는 않는다

DB 내장 함수 지원은 DB와 버전에 따라 다르다
내장 함수가 없으면 확장이나 애플리케이션 레벨 라이브러리로 생성하면 된다

## ULID

타임스탬프 10자(48비트) + 랜덤 16자(80비트)를 Base32로 인코딩한다

```
01ARZ3NDEKTSV4RRFFQ69G5FAV
├── 01ARZ3NDEK: 타임스탬프
└── TSV4RRFFQ69G5FAV: 랜덤
```

URL에 그대로 쓸 수 있고 대소문자를 구분하지 않는다
UUID v7과 성격이 비슷한데 문자열 표현이 더 짧고 깔끔하다
JavaScript는 `ulid`, Python은 `python-ulid` 패키지가 있다

참고로 Prisma의 `@default(cuid())`도 문자열 ID 생성 방식 중 하나다

```prisma
model User {
  id String @id @default(cuid())
}
```

## Snowflake ID

Twitter가 만든 방식이고 결과가 BIGINT(8 bytes)다

```
┌──────────────────────────────────────────────────────────┐
│ 1bit │ 41bits: timestamp(ms) │ 10bits: machine │ 12bits: seq │
└──────────────────────────────────────────────────────────┘
```

시간 기반이라 단조증가하고, 서버마다 machine ID가 달라서 분산 환경에서 독립적으로 만들 수 있다
8 bytes라서 UUID보다 가볍다

대신 machine ID를 직접 관리해야 한다
서버가 늘어날 때마다 번호를 할당하고 겹치지 않게 유지하는 운영 부담이 따라온다

## 성능 비교 (B-tree 기준)

```
삽입 성능 (빠름 → 느림):
INT 순차 > Snowflake > UUID v7 > ULID > UUID v4

저장 크기:
INT (4B) < BIGINT/Snowflake (8B) < UUID (16B)
```

실제 수치는 DB와 데이터 규모, 하드웨어에 따라 달라서 여기서는 순서만 본다
정확한 차이가 필요하면 내 워크로드로 직접 측정해야 한다

## 선택 가이드

```
외부 API로 ID가 노출되는가?
├── 아니오 (내부 시스템, 게임 백엔드)
│   └── INT / BIGINT
└── 예 (웹 API, REST, JWT에 포함)
    ├── 삽입 트래픽이 매우 큰가?
    │   ├── 예 → UUID v7 또는 Snowflake ID
    │   └── 아니오 → UUID v4로 충분
    └── 시간순 정렬, cursor 페이지네이션이 필요한가?
        ├── 예 → UUID v7
        └── 아니오 → UUID v4
```

## JARVIS AI의 선택

JARVIS AI는 UUID v4를 쓴다
ID가 외부 API로 노출되고, 서버는 단일 인스턴스고, 트래픽이 많지 않아서 v4로 충분하다고 판단했다

나중에 cursor 페이지네이션과 인덱스 성능이 필요해지면 UUID v7으로 옮기는 게 다음 개선 방향이다
