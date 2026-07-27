#!/bin/bash
# 매일 7:30 AM KST — drafts/ 새 파일 감지 + Claude Code로 검수/퀴즈 생성

BLOG_DIR="/Users/junghoshin/Documents/projects/wjdghtls95.github.io"
PROCESSED="$BLOG_DIR/.processed-drafts"

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
    PROMPT_FILE=$(mktemp /tmp/claude-prompt-XXXXXX.txt)
    cat > "$PROMPT_FILE" << PROMPT_EOF
블로그 draft 파일을 검수하고 퀴즈를 생성해줘.

파일 경로: $BLOG_DIR/$file

순서:
1. 파일 읽기
2. frontmatter tags 확인 → 분야 및 퀴즈 개수 결정:
   - tags에 'learning' 포함 → TypeScript/NestJS/AI 등 해당 기술 전문가로 검수, 퀴즈 10문제
   - tags에 'project' 포함 → 기술 전문가로 검수, 퀴즈 5문제
   - tags에 'devlog' 포함 → 검수만 (passed: true 처리), questions: []
3. 해당 분야 전문가로 검수 (기술 정확성, 오류 여부)
4. 결과를 /tmp/quiz_result.json 에 저장 (JSON만, 다른 텍스트 없이):
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
  ],
  "title": "글 제목",
  "study": "frontmatter의 study 값 (없으면 null)",
  "category": "learning 또는 project 또는 devlog",
  "questions": [
    객관식일 때:
    {
      "type": "multiple",
      "difficulty": "easy 또는 medium 또는 hard",
      "q": "질문",
      "options": ["A. 선택지", "B. 선택지", "C. 선택지", "D. 선택지"],
      "answer": "A",
      "section": "해당 H2 섹션 제목"
    }
    서술형일 때:
    {
      "type": "essay",
      "difficulty": "medium 또는 hard",
      "q": "질문",
      "modelAnswer": "모범 답안 — 핵심 개념을 2~3문장으로 정리",
      "section": "해당 H2 섹션 제목"
    }
  ]
  devlog는 questions: []
}
issues 없으면 빈 배열 []. 검수 실패 시 passed: false, questions: []
PROMPT_EOF

    unset NODE_OPTIONS && /opt/homebrew/bin/claude --allowedTools "Read,Write" -p "$(cat "$PROMPT_FILE")"
    rm -f "$PROMPT_FILE"

    if [ ! -f /tmp/quiz_result.json ]; then
      send_error "Claude 실행 실패 또는 quiz_result.json 미생성 (파일: $file)"
      break
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
