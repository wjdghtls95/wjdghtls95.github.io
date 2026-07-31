#!/bin/bash
# 매일 7:00 AM KST — blog-queue.md 백로그에서 다음 파일을 Obsidian에서 drafts/로 복사
# process-drafts.sh가 7:30 AM에 실행되므로 30분 여유
# cron에서 실행 시 PATH가 제한적이므로 필수 바이너리 명시
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

BLOG_DIR="/Users/junghoshin/Documents/projects/wjdghtls95.github.io"
OBSIDIAN_LEARNING="/Users/junghoshin/Documents/Obsidian Vault/학습"
QUEUE_FILE="$BLOG_DIR/blog-queue.md"
PROCESSED="$BLOG_DIR/.processed-drafts"
DRAFTS_DIR="$BLOG_DIR/drafts"

# .env 로드
if [ -f "$BLOG_DIR/.env" ]; then
  set -a
  # shellcheck source=/dev/null
  source "$BLOG_DIR/.env"
  set +a
fi

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

send_telegram() {
  local text="$1"
  curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=${text}" > /dev/null 2>&1
}

# 미처리 draft 수 확인 — 5개 이상이면 KV 큐가 충분히 찬 것으로 간주
unprocessed=0
for f in "$DRAFTS_DIR"/*.md "$DRAFTS_DIR"/*.mdx; do
  [ -f "$f" ] || continue
  base=$(basename "$f")
  [[ "$base" == "_TEMPLATE.md" ]] && continue
  rel="drafts/$base"
  grep -qxF "$rel" "$PROCESSED" 2>/dev/null || ((unprocessed++))
done

if [ "$unprocessed" -ge 5 ]; then
  log "미처리 draft ${unprocessed}개 — 큐 충분, 복사 스킵"
  exit 0
fi

# Python 파서 — 임시 파일로 분리 (heredoc + $() 조합 이슈 방지)
PARSER=$(mktemp /tmp/blog-sync-parser-XXXXXX.py)
cat > "$PARSER" << 'EOF'
import re, os, sys

blog_dir = "/Users/junghoshin/Documents/projects/wjdghtls95.github.io"
obsidian_dir = "/Users/junghoshin/Documents/Obsidian Vault/학습"
queue_file = os.path.join(blog_dir, "blog-queue.md")
processed_file = os.path.join(blog_dir, ".processed-drafts")
drafts_dir = os.path.join(blog_dir, "drafts")

processed = set()
if os.path.exists(processed_file):
    with open(processed_file) as f:
        for line in f:
            processed.add(line.strip())

with open(queue_file, encoding="utf-8") as f:
    content = f.read()

# ## 백로그 이후 섹션만 처리
m = re.search(r"## 백로그", content)
if not m:
    sys.exit(0)
backlog_text = content[m.start():]

# ## 스킵 이후는 제외
end_m = re.search(r"^## 스킵", backlog_text, re.MULTILINE)
if end_m:
    backlog_text = backlog_text[: end_m.start()]

for line in backlog_text.split("\n"):
    line = line.strip()
    if not line.startswith("|"):
        continue
    parts = [p.strip() for p in line.split("|")]
    if len(parts) < 5:
        continue
    num, title, source_raw, category = parts[1], parts[2], parts[3], parts[4]

    if not num or num == "#" or re.match(r"^[-:]+$", num):
        continue
    if "발행됨" in title:
        continue
    if "*" in source_raw:
        continue

    source = re.sub(r"`", "", source_raw).strip()
    if not source:
        continue

    obsidian_path = os.path.join(obsidian_dir, source)
    if not os.path.exists(obsidian_path):
        continue

    base_no_ext = os.path.splitext(source)[0]
    slug = base_no_ext.lower()
    slug = re.sub(r"[가-힣ㄱ-ㅎㅏ-ㅣ]+", "", slug)
    slug = re.sub(r"[^a-z0-9/]", "-", slug)
    slug = slug.replace("/", "-")
    slug = re.sub(r"-+", "-", slug).strip("-")

    if len(slug) < 3:
        continue

    draft_rel = "drafts/" + slug + ".md"
    draft_path = os.path.join(drafts_dir, slug + ".md")

    if draft_rel in processed or os.path.exists(draft_path):
        continue

    print(slug + "|" + title + "|" + source + "|" + category + "|" + obsidian_path)
    break
EOF

NEXT=$(python3 "$PARSER")
rm -f "$PARSER"

if [ -z "$NEXT" ]; then
  log "처리할 백로그 항목 없음 (모두 복사됨, 파일 없음, 또는 *병합 항목)"
  exit 0
fi

IFS='|' read -r SLUG TITLE SOURCE CATEGORY OBSIDIAN_PATH <<< "$NEXT"

log "복사 시작: $SOURCE → drafts/${SLUG}.md"
log "제목: $TITLE"

# tags 결정
case "$CATEGORY" in
  *JARVIS*|*프로젝트*) TAGS='["project"]' ;;
  *devlog*|*개발일지*) TAGS='["devlog"]' ;;
  *) TAGS='["learning"]' ;;
esac

TODAY=$(date +%Y-%m-%d)

# frontmatter + 원본 내용
{
  printf -- "---\n"
  printf "title: \"%s\"\n" "$TITLE"
  printf "description: \"%s\"\n" "$TITLE"
  printf "date: \"%s\"\n" "$TODAY"
  printf "tags: %s\n" "$TAGS"
  printf "study: \"학습/%s\"\n" "$SOURCE"
  printf -- "---\n\n"
  cat "$OBSIDIAN_PATH"
} > "$DRAFTS_DIR/${SLUG}.md"

# git 커밋 + 푸시
cd "$BLOG_DIR" || { log "블로그 디렉토리 접근 실패"; exit 1; }
git add "drafts/${SLUG}.md"
git commit -m "chore: add draft for ${SLUG}"
git push

NEXT_RUN=$(date -v+1d '+%Y-%m-%d' 2>/dev/null || date -d '+1 day' '+%Y-%m-%d' 2>/dev/null || echo "내일")
TELEGRAM_MSG="📥 새 draft 복사됨

제목: $TITLE
파일: drafts/${SLUG}.md

→ 다음 7:30 AM cron 실행 시 Claude 검수"

send_telegram "$TELEGRAM_MSG"
log "완료: drafts/${SLUG}.md"
