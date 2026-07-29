#!/bin/bash
# drafts/ 폴더 감시 — 파일 변경 시 process-drafts.sh 자동 실행
# launchd com.jarvis.blog-watcher 로 관리됨
# 수동 제어: blog-watch-on / blog-watch-off / blog-watch-status

BLOG_DIR="/Users/junghoshin/Documents/projects/wjdghtls95.github.io"
DRAFTS_DIR="$BLOG_DIR/drafts"
PROCESS_SCRIPT="$BLOG_DIR/scripts/process-drafts.sh"
DEBOUNCE_SECONDS=5

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"; }

log "drafts/ 감시 시작: $DRAFTS_DIR"
log "debounce: ${DEBOUNCE_SECONDS}초"

# --latency: 이벤트를 N초 동안 모아서 한 번만 발생시킴 (내장 debounce)
# -o: 이벤트 수만 출력 (파일 경로 불필요)
/opt/homebrew/bin/fswatch -o --latency "$DEBOUNCE_SECONDS" "$DRAFTS_DIR" | while read -r count; do
    log "변경 감지 (이벤트 ${count}건) → process-drafts.sh 실행"
    /bin/bash "$PROCESS_SCRIPT"
    log "process-drafts.sh 완료"
done
