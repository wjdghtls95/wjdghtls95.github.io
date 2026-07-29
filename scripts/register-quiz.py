"""
Claude Code가 생성한 /tmp/quiz_result.json 읽어서 KV 저장 + Telegram 발송.
LLM 없음 — HTTP 요청만.
"""
import os, sys, json, hashlib, re, glob, requests
from datetime import datetime, timezone, timedelta

BLOG_DIR = os.path.join(os.path.dirname(__file__), '..')

# .env 로드
env_path = os.path.join(BLOG_DIR, '.env')
if os.path.exists(env_path):
    with open(env_path) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith('#') and '=' in _line:
                _k, _v = _line.split('=', 1)
                os.environ.setdefault(_k.strip(), _v.strip())

CF_ACCOUNT_ID = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
KV_NAMESPACE_ID = os.environ["KV_NAMESPACE_ID"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
QUEUE_MAX = 5
CATEGORY_ORDER = ['learning', 'project', 'devlog']


# ===== HTTP helpers =====

def send_telegram(text, reply_markup=None):
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
    )


def get_kv(key):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{key}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}"})
    return None if resp.status_code == 404 else resp.text


def put_kv(key, value_str, expiration_ttl=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{key}"
    params = {"expiration_ttl": expiration_ttl} if expiration_ttl else {}
    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"},
        params=params,
        data=value_str.encode("utf-8"),
    )
    if not resp.ok:
        raise RuntimeError(f"KV 저장 실패 [{key}]: {resp.status_code} {resp.text}")


def save_error(msg):
    now_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d %H:%M KST")
    try:
        put_kv("LAST_ERROR", json.dumps({"time": now_kst, "message": msg}, ensure_ascii=False))
    except Exception as e:
        print(f"에러 KV 저장 실패: {e}")


# ===== Frontmatter parser =====

def parse_frontmatter(content):
    """frontmatter에서 tags / series / part 추출."""
    tags_m = re.search(r'^tags:\s*\[([^\]]+)\]', content, re.MULTILINE)
    tags = [t.strip().strip('"\'') for t in tags_m.group(1).split(',')] if tags_m else []

    series_m = re.search(r'^series:\s*["\']?(.+?)["\']?\s*$', content, re.MULTILINE)
    series = series_m.group(1).strip() if series_m else None

    part_m = re.search(r'^part:\s*(\d+)', content, re.MULTILINE)
    part = int(part_m.group(1)) if part_m else None

    category = next((c for c in CATEGORY_ORDER if c in tags), 'learning')

    return {"tags": tags, "category": category, "series": series, "part": part}


# ===== Last published post =====

def get_last_published():
    """src/content/blog/ 에서 가장 최근 발행 글 메타 반환."""
    blog_path = os.path.join(BLOG_DIR, 'src', 'content', 'blog')
    files = glob.glob(os.path.join(blog_path, '*.md')) + glob.glob(os.path.join(blog_path, '*.mdx'))
    if not files:
        return None

    latest_date = ""
    latest_meta = None
    for f in files:
        with open(f) as fp:
            content = fp.read()
        date_m = re.search(r'^date:\s*["\']?(\d{4}-\d{2}-\d{2})', content, re.MULTILINE)
        if date_m and date_m.group(1) > latest_date:
            latest_date = date_m.group(1)
            latest_meta = parse_frontmatter(content)

    return latest_meta


# ===== Queue sorting =====

def sort_queue(queue, last):
    """
    정렬 기준:
    1. 이전 글과 같은 series가 큐에 있으면 → 연속 발행 (part 순)
    2. 카테고리 로테이션: 이전 카테고리 다음 순서부터
    3. 같은 카테고리 내: 이전 글과 태그 겹침 최소화 (단 series 연속은 허용)
    """
    if not queue:
        return queue

    last_cat = last.get('category') if last else None
    last_series = last.get('series') if last else None
    last_tags = set(last.get('tags', [])) if last else set()

    # series 연속 발행 우선
    if last_series:
        series_cont = sorted(
            [q for q in queue if q.get('series') == last_series],
            key=lambda x: x.get('part') or 99,
        )
        if series_cont:
            rest = [q for q in queue if q.get('series') != last_series]
            return series_cont + sort_queue(rest, {**last, 'series': None})

    # 카테고리 로테이션 순서 계산
    if last_cat and last_cat in CATEGORY_ORDER:
        start = (CATEGORY_ORDER.index(last_cat) + 1) % len(CATEGORY_ORDER)
        ordered = CATEGORY_ORDER[start:] + CATEGORY_ORDER[:start]
    else:
        ordered = CATEGORY_ORDER

    def sort_key(item):
        cat = item.get('category', 'learning')
        cat_idx = ordered.index(cat) if cat in ordered else 99
        # 태그 겹침 (적을수록 앞)
        item_tags = set(t for t in item.get('tags', []) if t not in CATEGORY_ORDER)
        last_topic_tags = set(t for t in last_tags if t not in CATEGORY_ORDER)
        overlap = len(item_tags & last_topic_tags)
        part = item.get('part') or 99
        return (cat_idx, overlap, part)

    return sorted(queue, key=sort_key)


# ===== Format =====

def mark_as_processed(draft_file):
    """중복 방지 — 이미 있으면 skip."""
    path = os.path.join(BLOG_DIR, '.processed-drafts')
    if os.path.exists(path):
        with open(path) as f:
            if draft_file in f.read().splitlines():
                return
    with open(path, 'a') as f:
        f.write(draft_file + '\n')


def format_review(points):
    return "\n".join(f"  - {p}" for p in points) if points else "  - 이상 없음"


def format_issues(issues):
    if not issues:
        return ""
    blocks = []
    for i, issue in enumerate(issues, 1):
        if isinstance(issue, dict):
            issue_type = issue.get("type", "text")
            anchor = issue.get("anchor", "")
            what = issue.get("what", "")
            insert = issue.get("insert", issue.get("how", ""))
            position = issue.get("position", "after")

            if issue_type == "code":
                block = (
                    f"*{i}.* `{anchor}` 아래에 추가\n"
                    f"_{what}_\n"
                    f"{insert}"
                )
            elif issue_type == "opinion":
                block = (
                    f"*{i}.* 💬 *의견/경험 추가 제안*\n"
                    f"`{anchor}` 뒤에\n"
                    f"_{what}_"
                )
            elif issue_type == "opinion_fix":
                block = (
                    f"*{i}.* 💬 *의견 어색함*\n"
                    f"`{anchor}`\n"
                    f"_{what}_"
                )
            else:
                action = "→ 이 문장으로 교체" if position == "replace" else "→ 이 문장 뒤에 추가"
                # 코드블록 포함 시 이탤릭(_..._) 감싸면 Telegram Markdown 충돌 → 그대로 출력
                insert_text = insert if insert and "```" in insert else f"_{insert}_" if insert else ""
                block = (
                    f"*{i}.* `{anchor}`\n"
                    f"{action}:\n"
                    f"{insert_text}"
                )
        else:
            block = f"*{i}.* {issue}"
        blocks.append(block)
    return "\n\n".join(blocks)


# ===== Core: register to queue =====

def register_to_queue(result, draft_file, meta):
    queue_raw = get_kv("PENDING_QUEUE")
    queue = json.loads(queue_raw) if queue_raw else []

    if len(queue) >= QUEUE_MAX:
        send_telegram(f"⚠️ 큐가 꽉 찼습니다 ({QUEUE_MAX}개)\n미등록: _{result['title']}_")
        return False

    slug = hashlib.md5(draft_file.encode()).hexdigest()[:8]
    quiz_key = f"pending_quiz_{slug}"

    put_kv(quiz_key, json.dumps({
        "title": result["title"],
        "questions": result["questions"],
        "draftFile": draft_file,
        "userAnswers": {},
    }, ensure_ascii=True), expiration_ttl=7 * 86400)

    # 큐 아이템에 메타 포함 (정렬용)
    queue.append({
        "file": draft_file,
        "title": result["title"],
        "quizKey": quiz_key,
        "category": meta["category"],
        "tags": meta["tags"],
        "series": meta["series"],
        "part": meta["part"],
    })

    # 정렬
    last = get_last_published()
    queue = sort_queue(queue, last)
    put_kv("PENDING_QUEUE", json.dumps(queue, ensure_ascii=True))

    if not get_kv("NEXT_QUIZ_DATE"):
        today_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
        put_kv("NEXT_QUIZ_DATE", today_kst)

    quiz_date = get_kv("NEXT_QUIZ_DATE")

    mark_as_processed(draft_file)

    try:
        put_kv("LAST_ERROR", json.dumps({"time": None, "message": None}, ensure_ascii=False))
    except Exception:
        pass

    study = result.get("study")
    study_line = f"\n📚 *퀴즈 전에 읽어보세요:*\n  `{study}`" if study else ""
    series_line = f"\n📚 시리즈: _{meta['series']}_ (Part {meta['part']})" if meta.get('series') else ""
    question_count = len(result.get("questions", []))
    review_text = format_review(result.get("review_points", []))

    # 큐 순서 표시
    queue_pos = next((i + 1 for i, q in enumerate(queue) if q["quizKey"] == quiz_key), "?")
    queue_total = len(queue)

    send_telegram(
        f"📥 *퀴즈 등록됐습니다*\n\n"
        f"제목: _{result['title']}_\n"
        f"카테고리: {meta['category']} ({question_count}문제)"
        f"{series_line}"
        f"{study_line}\n\n"
        f"✅ *검수 통과*\n{review_text}\n\n"
        f"📋 큐 순서: {queue_pos}/{queue_total}\n"
        f"퀴즈 예정: {quiz_date} 18:00 KST"
    )
    print(f"완료: {result['title']} (큐 {queue_pos}/{queue_total})")
    return True


# ===== Entry point =====

# --save-error 모드
if len(sys.argv) > 1 and sys.argv[1] == "--save-error":
    save_error(sys.argv[2] if len(sys.argv) > 2 else "알 수 없는 에러")
    sys.exit(0)

# --check-revisions 모드 (cron 시작 시 실행 — Worker가 REVISION_LIST에 기록한 파일을 .processed-drafts에서 제거)
if len(sys.argv) > 1 and sys.argv[1] == "--check-revisions":
    raw = get_kv("REVISION_LIST")
    if not raw:
        sys.exit(0)
    try:
        revision_files = json.loads(raw)
    except Exception:
        sys.exit(0)
    if not revision_files:
        sys.exit(0)

    processed_path = os.path.join(BLOG_DIR, '.processed-drafts')
    if os.path.exists(processed_path):
        with open(processed_path) as f:
            lines = f.readlines()
        new_lines = [l for l in lines if l.strip() not in revision_files]
        with open(processed_path, 'w') as f:
            f.writelines(new_lines)

    put_kv("REVISION_LIST", "[]")
    print(f"수정 요청 파일 {len(revision_files)}개 재처리 대기 해제: {revision_files}")
    sys.exit(0)

DRAFT_FILE = sys.argv[1]

result_path = "/tmp/quiz_result.json"
if not os.path.exists(result_path):
    msg = f"quiz_result.json 없음 (파일: {DRAFT_FILE})"
    save_error(msg)
    send_telegram(f"❌ *파이프라인 실패*\n\n{msg}")
    sys.exit(1)

with open(result_path) as f:
    result = json.load(f)

os.remove(result_path)

# draft 파일에서 직접 메타 파싱 (series, part, tags, category)
with open(os.path.join(BLOG_DIR, DRAFT_FILE)) as f:
    draft_content = f.read()

meta = parse_frontmatter(draft_content)
issues = result.get("issues", [])

# ── 검수 실패 — opinion 전용이면 개선 제안으로 격하, 아니면 버튼 포함 실패 알림 ──
if not result.get("passed"):
    blocking = [i for i in issues if isinstance(i, dict) and i.get("type") not in ("opinion", "opinion_fix")]
    if not blocking:
        # opinion 이슈만 있으면 passed: true로 처리
        result["passed"] = True
    else:
        review_text = format_review(result.get("review_points", []))
        issues_text = format_issues(issues)
        slug = hashlib.md5(DRAFT_FILE.encode()).hexdigest()[:8]
        pending_key = f"pending_approval_{slug}"
        put_kv(pending_key, json.dumps({**result, **meta, "draftFile": DRAFT_FILE}, ensure_ascii=True), expiration_ttl=7 * 86400)
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ 그냥 올리기", "callback_data": json.dumps({"a": "approve", "k": slug})},
                {"text": "✏️ 수정할게요", "callback_data": json.dumps({"a": "reject", "k": slug})},
            ]]
        }
        send_telegram(
            f"❌ *검수 실패*\n\n"
            f"파일: `{DRAFT_FILE}`\n\n"
            f"✅ *잘된 점*\n{review_text}\n\n"
            f"⚠️ *수정 필요*\n{issues_text}\n\n"
            f"어떻게 하시겠습니까?",
            reply_markup=reply_markup,
        )
        save_error(f"검수 실패 — {DRAFT_FILE}\n" + "\n".join(
            i if isinstance(i, str) else f"{i.get('anchor', '')} — {i.get('what', '')}"
            for i in issues
        ))
        mark_as_processed(DRAFT_FILE)
        sys.exit(0)

# ── devlog → 퀴즈 없이 안내 ──
if meta["category"] == "devlog":
    review_text = format_review(result.get("review_points", []))
    send_telegram(
        f"✅ *devlog 검수 완료*\n\n"
        f"제목: _{result['title']}_\n\n"
        f"✅ *검수 통과*\n{review_text}\n\n"
        f"`direct/` 폴더로 이동 후 push하면 바로 발행됩니다"
    )
    mark_as_processed(DRAFT_FILE)
    sys.exit(0)

# ── 개선 제안 있음 → 인라인 버튼 ──
if issues:
    review_text = format_review(result.get("review_points", []))
    issues_text = format_issues(issues)

    slug = hashlib.md5(DRAFT_FILE.encode()).hexdigest()[:8]
    pending_key = f"pending_approval_{slug}"
    # meta + draftFile 포함해서 저장 (Worker의 approve/reject 핸들러에서 파일 경로 참조)
    put_kv(pending_key, json.dumps({**result, **meta, "draftFile": DRAFT_FILE}, ensure_ascii=True), expiration_ttl=7 * 86400)

    reply_markup = {
        "inline_keyboard": [[
            {"text": "✅ 그냥 올리기", "callback_data": json.dumps({"a": "approve", "k": slug})},
            {"text": "✏️ 수정할게요", "callback_data": json.dumps({"a": "reject", "k": slug})},
        ]]
    }

    send_telegram(
        f"⚠️ *개선 제안 있음*\n\n"
        f"제목: _{result['title']}_\n\n"
        f"✅ *잘된 점*\n{review_text}\n\n"
        f"⚠️ *개선 제안*\n{issues_text}\n\n"
        f"어떻게 하시겠습니까?",
        reply_markup=reply_markup,
    )
    # 재처리 방지 — "수정할게요" 클릭 시 Worker가 REVISION_LIST에 추가해 다음 cron에서 제거
    mark_as_processed(DRAFT_FILE)
    print(f"개선 제안 — 버튼 응답 대기 중: {result['title']}")
    sys.exit(0)

# ── 이슈 없음 → 바로 큐 등록 ──
register_to_queue(result, DRAFT_FILE, meta)
