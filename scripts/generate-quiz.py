import os
import json
import hashlib
import requests
from datetime import datetime, timezone, timedelta
from openai import OpenAI

DRAFT_FILE = os.environ["DRAFT_FILE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CF_ACCOUNT_ID = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
KV_NAMESPACE_ID = "36dfe08248484462b941e184e6e79c39"
QUEUE_MAX = 5

with open(DRAFT_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# ===== KV Helpers =====

def get_kv(key):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{key}"
    resp = requests.get(url, headers={"Authorization": f"Bearer {CF_API_TOKEN}"})
    if resp.status_code == 404:
        return None
    return resp.text

def put_kv(key, value_str, expiration_ttl=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{key}"
    params = {}
    if expiration_ttl:
        params["expiration_ttl"] = expiration_ttl
    requests.put(
        url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"},
        params=params,
        data=value_str.encode("utf-8"),
    )

def send_telegram(text):
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
    )

# ===== Quiz Generation =====

client = OpenAI(api_key=OPENAI_API_KEY)

prompt = f"""다음 글을 읽고 퀴즈 10문제를 만들어줘.

규칙:
- 글의 H2 섹션이 여러 개면 각 섹션에서 반드시 1문제 이상 출제
- 글 전체를 다 읽어야 풀 수 있어야 함
- 객관식 7문제 (easy 2, medium 3, hard 2)
- 서술형 3문제 (medium 1, hard 2)
- 아래 JSON 형식으로만 반환 (다른 텍스트 없이)

{{
  "title": "글 제목",
  "questions": [
    {{"type": "multiple", "difficulty": "easy", "q": "질문", "options": ["A. 선택지", "B. 선택지", "C. 선택지", "D. 선택지"], "answer": "A", "section": "섹션명"}},
    {{"type": "essay", "difficulty": "hard", "q": "질문", "section": "섹션명"}}
  ]
}}

글 내용:
{content}"""

response = client.chat.completions.create(
    model="gpt-4o-mini",
    max_tokens=2000,
    response_format={"type": "json_object"},
    messages=[{"role": "user", "content": prompt}],
)

quiz = json.loads(response.choices[0].message.content)

# 객관식 먼저, 서술형 나중
mc = [q for q in quiz["questions"] if q["type"] == "multiple"]
essay = [q for q in quiz["questions"] if q["type"] == "essay"]
quiz["questions"] = mc + essay
quiz["draftFile"] = DRAFT_FILE
quiz["content"] = content[:2000]
quiz["userAnswers"] = {}

# ===== Queue Management =====

# 큐 상한 체크
queue_raw = get_kv("PENDING_QUEUE")
queue = json.loads(queue_raw) if queue_raw else []

if len(queue) >= QUEUE_MAX:
    send_telegram(
        f"⚠️ 큐가 꽉 찼습니다 ({QUEUE_MAX}개)\n"
        f"기존 글이 발행된 후 다시 push해주세요\n\n"
        f"미등록: _{quiz['title']}_"
    )
    raise SystemExit(0)

# 퀴즈 데이터를 고유 키로 저장 (7일 TTL)
slug = hashlib.md5(DRAFT_FILE.encode()).hexdigest()[:8]
quiz_key = f"pending_quiz_{slug}"
put_kv(quiz_key, json.dumps(quiz, ensure_ascii=True), expiration_ttl=7 * 86400)

# 큐에 추가
queue.append({"file": DRAFT_FILE, "title": quiz["title"], "quizKey": quiz_key})
put_kv("PENDING_QUEUE", json.dumps(queue, ensure_ascii=True))

# 첫 번째 항목이면 NEXT_QUIZ_DATE를 오늘로 설정
existing_date = get_kv("NEXT_QUIZ_DATE")
if not existing_date:
    today_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    put_kv("NEXT_QUIZ_DATE", today_kst)

# 퀴즈 예정일 읽기
quiz_date = get_kv("NEXT_QUIZ_DATE")
queue_position = len(queue)

send_telegram(
    f"📥 *퀴즈 등록됐습니다*\n\n"
    f"제목: _{quiz['title']}_\n"
    f"큐 위치: {queue_position}번째\n"
    f"퀴즈 예정: {quiz_date} 18:00 KST"
)
