---
title: "BullMQ vs SQS — 왜 BullMQ를 선택했나"
description: "JARVIS 알림 시스템 구축 중 SQS 대신 BullMQ를 선택한 이유와 실측 수치"
pubDate: 2026-07-23
category: "기술"
tags: ["JARVIS", "BullMQ", "NestJS", "Redis"]
series: "JARVIS AI 개발기"
---

## 문제 상황

JARVIS 알림 시스템을 구축하면서 큐 시스템 선택이 필요했다. AWS SQS와 BullMQ 두 가지를 검토했다.

## SQS vs BullMQ 비교

| 항목 | SQS | BullMQ |
|---|---|---|
| 최소 지연 | 15분 | ms 단위 |
| repeat job | 없음 | 있음 |
| Redis 필요 | 없음 | 있음 |
| 비용 | 요청당 | Redis 비용만 |

## 선택 이유

Railway 환경에서 Redis를 이미 사용 중이라 추가 비용 없이 BullMQ를 쓸 수 있었다. repeat job 지원이 결정적이었다.

## 배운 점

`addRepeatableJob()`에 결정론적 key를 넣지 않으면 `removeRepeatableByKey`가 불가능하다. 반드시 key를 명시해야 한다.
 
