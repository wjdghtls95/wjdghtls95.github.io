# 블로그 + 퀴즈 자동화

Astro Micro 기반 개인 기술 블로그 + Telegram 퀴즈 자동화 시스템.

**블로그**: [wjdghtls95.github.io](https://wjdghtls95.github.io)

---

## 글 발행 방법

### 방법 1 — 퀴즈 심사 후 발행 (`drafts/`)

```
drafts/*.md 파일 push
  → LLM이 퀴즈 10문제 생성 → Telegram 전송
  → 매일 18:00 KST 퀴즈 전송
  → 통과 → 다음날 08:00 KST 자동 발행
```

### 방법 2 — 즉시 발행 (`direct/`)

```
direct/*.md 파일 push → 퀴즈 없이 바로 발행
```

---

## 퀴즈 LLM 설정

기본 프로바이더는 **Anthropic**. `LLM_PROVIDER` Secret으로 변경 가능.

### 지원 프로바이더

| 프로바이더 | `LLM_PROVIDER` 값 | 필요한 Secret | 기본 모델 |
|-----------|-----------------|--------------|---------|
| Anthropic (기본) | `anthropic` | `ANTHROPIC_API_KEY` | `claude-haiku-4-5-20251001` |
| Google Gemini | `gemini` | `GEMINI_API_KEY` | `gemini-2.0-flash` |
| OpenAI | `openai` | `OPENAI_API_KEY` | `gpt-4o-mini` |

### GitHub Secrets 설정

**필수** (공통):
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `CF_ACCOUNT_ID`, `CF_API_TOKEN`, `KV_NAMESPACE_ID`

**LLM 키 (사용하는 프로바이더 것만)**:
- `ANTHROPIC_API_KEY` — Anthropic 사용 시
- `GEMINI_API_KEY` — Gemini 사용 시
- `OPENAI_API_KEY` — OpenAI 사용 시

**선택** (기본값 있음):
- `LLM_PROVIDER` — 미설정 시 `anthropic` 사용
- `LLM_MODEL` — 미설정 시 각 프로바이더 기본 모델 사용

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
drafts/       ← 퀴즈 심사 대기 글 (push 시 파이프라인 트리거)
direct/       ← 즉시 발행 글
src/
  content/
    blog/     ← 발행된 글
    projects/ ← 프로젝트 목록
scripts/
  generate-quiz.py  ← LLM 퀴즈 생성 + Cloudflare KV 등록
.github/workflows/
  quiz-pipeline.yml   ← drafts push → 퀴즈 생성
  publish.yml         ← 퀴즈 통과 후 자동 발행
  direct-publish.yml  ← direct push → 즉시 발행
  deploy.yml          ← GitHub Pages 배포
```
