---
title: "파이프라인 테스트 글"
description: "퀴즈 파이프라인 동작 확인용 임시 글입니다"
date: "2026-07-27"
tags: ["테스트"]
draft: true
---

## 테스트 섹션 A

이 글은 퀴즈 파이프라인이 정상 동작하는지 확인하기 위한 임시 글입니다.

LLM이 이 글을 읽고 퀴즈를 생성한 뒤 Telegram으로 전송합니다.
퀴즈 생성이 성공하면 Cloudflare KV에 등록되고 Telegram 알림이 옵니다.

## 테스트 섹션 B

파이프라인 구성 요소:

- GitHub Actions에서 LLM 퀴즈 생성
- Cloudflare KV에 퀴즈 데이터 저장
- Telegram 봇으로 알림 전송

확인 후 이 글은 삭제됩니다. (재시도 4)
