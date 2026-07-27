# 블로그 + 퀴즈 자동화

Astro Micro 기반 개인 기술 블로그 + Telegram 퀴즈 자동화 시스템.

**블로그**: [wjdghtls95.github.io](https://wjdghtls95.github.io)

---

## 전체 파이프라인

```
매일 7:30 AM KST (로컬 crontab)
  → drafts/ 새 파일 감지
  → Claude Code가 전문가 검수 + 퀴즈 생성 (외부 LLM API 없음)
  → Telegram 알림

이슈 없음  → 큐 자동 등록
개선 제안  → Telegram 버튼 ("그냥 올리기" / "수정할게요")
검수 실패  → Telegram 에러 알림

매일 18:00 KST (Cloudflare Worker cron)
  → 큐에서 첫 번째 글 꺼내 퀴즈 전송
  → 퀴즈 통과 (70점+) → 다음날 08:00 KST 자동 발행
  → 실패 → 30분마다 재시도
```

---

## 글 발행 방법

### 방법 1 — 퀴즈 심사 후 발행 (`drafts/`)

1. `drafts/` 폴더에 `.md` 파일 작성
2. 저장만 하면 됨 (다음날 7:30 AM에 자동 처리)
3. Telegram에서 검수 결과 확인 후 발행 여부 결정

### 방법 2 — 즉시 발행 (`direct/`)

```
direct/*.md push → 퀴즈 없이 바로 발행 (devlog용)
```

---

## Frontmatter 형식

```yaml
---
title: "제목"
description: "설명"
date: "2026-07-27"
tags: ["learning", "TypeScript"]   # learning / project / devlog 중 하나 필수
study: "학습/TypeScript/파일명.md"  # 선택 — 퀴즈 전 읽어볼 Obsidian 노트 경로
series: "시리즈명"                   # 선택 — 연속 글일 때
part: 1                              # 선택 — series와 함께 사용
---
```

| 태그 | 퀴즈 | 발행 경로 |
|------|------|---------|
| `learning` | 10문제 | drafts/ → 큐 |
| `project` | 5문제 | drafts/ → 큐 |
| `devlog` | 없음 | direct/ 로 이동 후 push |

---

## Telegram 명령어

| 명령어 | 기능 |
|--------|------|
| `/start` | 봇 상태 및 큐 확인 |
| `/quiz` | 퀴즈 즉시 시작 |
| `/queue` | 대기 목록 확인 |
| `/먼저 N` | 큐 순서 변경 (예: `/먼저 2`) |
| `/skip` | 퀴즈 건너뛰고 내일 발행 |
| `/postpone` | 퀴즈 내일로 미루기 |
| `/error` | 마지막 파이프라인 에러 확인 |

---

## 큐 정렬 로직

새 글이 큐에 들어올 때 자동 정렬:

1. 이전 발행 글과 같은 `series` → 연속 발행 (part 순)
2. 카테고리 로테이션: `learning → project → devlog`
3. 같은 카테고리 내: 이전 글과 태그 겹침 최소화

---

## 개선 제안 처리

검수에서 이슈가 나오면 Telegram 버튼으로 선택:

- **그냥 올리기** → 수정 없이 큐에 바로 등록
- **수정할게요** → `drafts/` 파일 수정 후 저장 (push 불필요) → 다음날 7:30 AM 자동 재처리

---

## 로컬 설정

### 필요 파일

```
.env                  ← 크레덴셜 (gitignore)
.processed-drafts     ← 처리된 파일 추적 (gitignore)
scripts/
  process-drafts.sh   ← crontab 진입점
  register-quiz.py    ← KV 저장 + Telegram 발송
```

### `.env` 형식

```
CF_ACCOUNT_ID=...
CF_API_TOKEN=...
KV_NAMESPACE_ID=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
```

### crontab 설정

```bash
crontab -e
# 추가:
30 7 * * * /bin/bash /절대경로/scripts/process-drafts.sh >> /tmp/blog-cron.log 2>&1
```

### 퀴즈봇 (Cloudflare Worker)

```bash
cd ~/Documents/projects/quiz-bot
unset NODE_OPTIONS && npx wrangler deploy
```

---

## GitHub Actions

| 워크플로우 | 역할 |
|-----------|------|
| `deploy.yml` | GitHub Pages 배포 |
| `publish.yml` | 퀴즈 통과 후 drafts → src/content/blog 이동 |
| `direct-publish.yml` | direct/ push → 즉시 발행 |
| ~~`quiz-pipeline.yml`~~ | 비활성화 (로컬 cron으로 대체) |

---

## 로컬 개발

```bash
npm install
npm run dev       # localhost:4321
npm run build
npm run preview
```

---

## 프로젝트 구조

```
drafts/           ← 검수 대기 글
direct/           ← 즉시 발행 글 (devlog)
src/content/blog/ ← 발행 완료 글
scripts/
  process-drafts.sh   ← 7:30 AM cron 진입점
  register-quiz.py    ← KV + Telegram 핸들러
~/Documents/projects/quiz-bot/  ← Cloudflare Worker (퀴즈봇)
```
