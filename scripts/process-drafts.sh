#!/bin/bash
# 매일 7:30 AM KST — drafts/ 새 파일 감지 + Claude Code로 검수/퀴즈 생성

BLOG_DIR="/Users/junghoshin/Documents/projects/wjdghtls95.github.io"
PROCESSED="$BLOG_DIR/.processed-drafts"

# 동시 실행 방지 — launchd + fswatch가 겹칠 경우 두 번째 실행 즉시 종료 (macOS: PID 방식)
LOCK_FILE="/tmp/blog-process.lock"
if [ -f "$LOCK_FILE" ] && kill -0 "$(cat "$LOCK_FILE")" 2>/dev/null; then
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] 이미 실행 중 (PID: $(cat "$LOCK_FILE")) — 건너뜀"
  exit 0
fi
echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

# .env 로드 (Telegram 에러 알림용)
if [ -f "$BLOG_DIR/.env" ]; then
  export $(grep -v '^#' "$BLOG_DIR/.env" | xargs)
fi

send_error() {
  local msg="$1"
  echo "[$(date)] ERROR: $msg"
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    -d "text=❌ *파이프라인 실패*%0A%0A${msg}" \
    -d "parse_mode=Markdown" > /dev/null
  python3 "$BLOG_DIR/scripts/register-quiz.py" --save-error "$msg"
}

cd "$BLOG_DIR" || { send_error "블로그 디렉토리 접근 실패: $BLOG_DIR"; exit 1; }

# "수정할게요" 클릭된 파일 .processed-drafts에서 제거 (재처리 대기)
python3 "$BLOG_DIR/scripts/register-quiz.py" --check-revisions

found=0
for file in drafts/*.md drafts/*.mdx; do
  [ -f "$file" ] || continue
  if ! grep -qxF "$file" "$PROCESSED" 2>/dev/null; then
    echo "[$(date)] 새 draft 감지: $file"
    found=1

    rm -f /tmp/quiz_result.json

    # 프롬프트를 임시 파일로 분리 — 인라인 백틱이 셸 명령으로 실행되는 것 방지
    PROMPT_FILE="/tmp/claude-prompt-$$.txt"
    cat > "$PROMPT_FILE" << PROMPT_EOF
블로그 draft 파일을 블로그 글로 변환하고, 검수하고, 퀴즈를 생성해줘.

파일 경로: $BLOG_DIR/$file

---

## 순서

### 1단계 — 파일 읽기
파일을 읽는다.

### 2단계 — 블로그 글로 재작성 (조건부)
frontmatter에 \`rewritten: true\`가 있으면 이 단계를 완전히 건너뛴다 (사용자가 직접 수정한 파일이므로).
\`rewritten: true\`가 없으면 Obsidian 학습 노트를 블로그 아티클로 변환해서 같은 파일 경로에 덮어쓴다.
재작성 후 frontmatter에 \`rewritten: true\` 한 줄을 추가한다 (다음 재처리 시 덮어쓰기 방지용).

**재작성 규칙:**

- frontmatter(---...---) 에서 title·date·tags·study·rewritten 필드는 그대로 유지.
- description 필드는 글 내용 기반으로 검색 결과에서 보여줄 한 줄 요약으로 새로 작성한다 (title과 달라야 함, 40~80자).
- Obsidian 전용 문법 제거:
  - \`> [!note]-\`, \`> [!tip]-\`, \`> [!warning]-\` 등 callout → 일반 텍스트로 흡수
  - \`_Updated: ..._\` 줄 삭제
  - \`[[내부링크]]\` → 링크 텍스트만 남기기
- 학습 노트 구조(개념 나열) → 블로그 글 구조로 전환:
  - 첫 문장부터 핵심으로 들어간다. "이 글에서는 X를 알아보겠습니다" 금지
  - 독자가 실제로 겪는 상황이나 문제에서 시작하면 좋다
  - 섹션 간 자연스러운 흐름이 있어야 한다 (각 섹션이 독립된 메모처럼 끊기면 안 됨)
- 코드 예시는 ✅ ❌ 패턴 적극 사용
- 빠진 중요 개념이 있으면 자연스럽게 추가한다

**절대 금지 (AI 티 나는 패턴):**
- "~에 대해 알아보겠습니다" / "~를 살펴보겠습니다"
- "결론적으로" / "정리하자면" / "마치며"
- "TypeScript는 강력한 언어입니다" 같은 generic 도입부
- 완벽하게 N개로 나열 ("3가지 방법", "5가지 장점")
- 모든 섹션에 들어가며/결론 달기
- 존댓말과 반말 혼용 → 전체 반말 유지 (예: "쓴다", "된다", "있다")

**참고할 기존 글 스타일 (이 tone으로):**
직접적이고 짧은 문장. 코드 예시 중심. 개발자가 실제 경험에서 쓰는 말투.
예) "as는 타입을 강제로 덮어씌운다. 틀려도 오류가 안 난다."
예) "satisfies는 검사만 하고 추론된 타입은 유지한다."

재작성이 끝나면 파일에 Write한다.

### 3단계 — frontmatter tags 확인 → 분야 결정
재작성된 파일을 기준으로:
- tags에 'learning' → 해당 기술 전문가로 검수, 퀴즈 10문제
- tags에 'project' → 기술 전문가로 검수, 퀴즈 5문제
- tags에 'devlog' → 검수만 (passed: true), questions: []

### 4단계 — 기술 전문가로 검수
두 가지를 동시에 체크한다:

**기술 검수:**
- 내용의 정확성, 오류 여부
- 중요한 개념이 빠졌는지 (코드 예시 누락 포함)

**의견/경험 검수:**
- 이 글에서 저자(백엔드 개발자, JARVIS AI 개인 프로젝트 진행 중)의 의견이나 실제 경험이 들어가면
  훨씬 읽힐 만한 지점이 있는가?
- 예시: "enum vs as const 중 실제로 뭘 쓰는지", "제네릭을 처음 쓸 때 어디서 막혔는지",
  "이 패턴을 알고 나서 실제 코드에서 어떻게 바뀌었는지"
- frontmatter에 \`rewritten: true\`가 있으면 (재처리 파일) → 저자가 의견을 추가했는지 확인하고,
  추가된 의견이 글의 흐름과 자연스럽게 맞는지, 어색하지 않은지 검수한다

### 5단계 — 결과를 /tmp/quiz_result.json 에 저장 (JSON만, 다른 텍스트 없이)
{
  "passed": true 또는 false,
  "review_points": ["잘된 점1", "잘된 점2"],
  "issues": [
    코드 추가일 때:
    {
      "type": "code",
      "anchor": "이 섹션 제목 (예: ## 역방향 매핑)",
      "what": "무엇이 빠졌는지 한 줄",
      "insert": "삽입할 코드 블럭 (\`\`\`ts ... \`\`\` 형식 포함)"
    }
    개념/텍스트 추가일 때:
    {
      "type": "text",
      "anchor": "파일에서 Ctrl+F로 찾을 기준 문장 (파일에 실제 존재하는 문장 그대로)",
      "position": "after 또는 replace",
      "what": "무엇이 문제인지 한 줄",
      "insert": "추가하거나 교체할 실제 문장"
    }
    저자 의견/경험 추가가 필요한 지점일 때:
    {
      "type": "opinion",
      "anchor": "파일에서 Ctrl+F로 찾을 기준 문장 (실제 존재하는 문장 그대로)",
      "position": "after",
      "what": "어떤 의견이나 경험을 넣으면 좋을지 — 구체적인 질문 형태로",
      "insert": null
    }
    재처리 시 추가된 의견이 어색할 때:
    {
      "type": "opinion_fix",
      "anchor": "어색한 문장 그대로",
      "position": "replace",
      "what": "어떤 부분이 어색한지 + 왜",
      "insert": null
    }
  ],
  "title": "글 제목",
  "study": "frontmatter의 study 값 (없으면 null)",
  "category": "learning 또는 project 또는 devlog",
  "questions": [
    {
      "type": "multiple",
      "difficulty": "easy 또는 medium 또는 hard",
      "q": "질문",
      "options": ["A. 선택지", "B. 선택지", "C. 선택지", "D. 선택지"],
      "answer": "A",
      "explanation": "정답이 A인 이유를 1~2문장으로 — 틀린 선택지가 왜 틀렸는지 포함",
      "section": "해당 H2 섹션 제목"
    }
  ]
  devlog는 questions: []
}
issues 없으면 빈 배열 []. 검수 실패 시 passed: false여도 questions는 반드시 생성 (devlog 제외). questions: []는 devlog만.

**퀴즈 품질 기준 (반드시 지킬 것):**

모든 문제는 객관식(type: "multiple")만. 서술형 금지.

목표: 개념을 이해하고 코드에 적용할 수 있는가를 체크하는 것.
암기나 사실 확인이 목적이 아니다.

절대 금지 문제 유형:
- 버전/연도 ("TypeScript X.Y에서 추가된", "2023년에 도입된")
- 정의 암기 ("~의 정의로 올바른 것은?", "~란 무엇인가?")
- 이름 맞추기 ("이 연산자의 이름은?", "이 패턴의 공식 명칭은?")
- 공식 문서 발췌 ("공식 문서에 따르면")

좋은 문제의 기준:
- 인라인 코드로 짧은 스니펫을 주고 "이 코드의 결과/타입은?" → 이해하면 풀 수 있음
- 두 패턴의 차이를 묻는 것 → 실제로 써봐야 아는 것
- "언제 A 대신 B를 써야 하는가?" → 판단력을 체크하는 것
- 잘못된 코드를 주고 "무엇이 문제인가?" → 실전 디버깅 능력
PROMPT_EOF

    unset NODE_OPTIONS && /opt/homebrew/bin/claude --allowedTools "Read,Write" -p "$(cat "$PROMPT_FILE")"
    rm -f "$PROMPT_FILE"

    if [ ! -f /tmp/quiz_result.json ]; then
      send_error "Claude 실행 실패 또는 quiz_result.json 미생성 (파일: $file)"
      break
    fi

    # 재작성된 draft 파일 git commit + push (GitHub Actions publish 시 최신 버전 사용하도록)
    if git diff --quiet "$file" 2>/dev/null; then
      echo "[$(date)] draft 변경 없음 — git commit 스킵"
    else
      git add "$file"
      git commit -m "chore: rewrite $(basename "$file" .md) as blog post"
      git push
    fi

    python3 "$BLOG_DIR/scripts/register-quiz.py" "$file"
    if [ $? -ne 0 ]; then
      send_error "register-quiz.py 실패 (파일: $file) — /tmp/blog-cron.log 확인"
    fi
    break
  fi
done

if [ $found -eq 0 ]; then
  echo "[$(date)] 새 draft 없음 — 종료"
fi
