import os
import json
import hashlib
import requests
from datetime import datetime, timezone, timedelta

DRAFT_FILE = os.environ["DRAFT_FILE"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CF_ACCOUNT_ID = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
KV_NAMESPACE_ID = os.environ["KV_NAMESPACE_ID"]
QUEUE_MAX = 5

# ===== LLM Provider =====
# LLM_PROVIDER: openai (default) | anthropic | groq | ollama | openai-compatible
# 각 프로바이더에 맞는 환경변수만 설정하면 됨
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "anthropic")

with open(DRAFT_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# frontmatter에서 source 파일 경로 파싱
import re as _re
_source_match = _re.search(r'^source:\s*(.+)$', content, _re.MULTILINE)
SOURCE_FILE = _source_match.group(1).strip() if _source_match else None

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

QUIZ_PROMPT_KO = f"""다음 글을 읽고 퀴즈 10문제를 만들어줘.

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


def call_llm(prompt: str) -> str:
    """LLM_PROVIDER에 맞게 퀴즈 생성 요청. 모두 JSON 문자열 반환."""

    if LLM_PROVIDER == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=os.environ.get("LLM_MODEL", "claude-haiku-4-5-20251001"),
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    elif LLM_PROVIDER == "groq":
        # Groq은 OpenAI SDK의 base_url만 바꾸면 됨 (무료 한도 있음)
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ["GROQ_API_KEY"],
            base_url="https://api.groq.com/openai/v1",
        )
        resp = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "llama-3.1-8b-instant"),
            max_tokens=2000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content

    elif LLM_PROVIDER == "openai-compatible":
        # Ollama, Together AI, OpenRouter 등 OpenAI 호환 엔드포인트
        from openai import OpenAI
        client = OpenAI(
            api_key=os.environ.get("LLM_API_KEY", "ollama"),
            base_url=os.environ["LLM_BASE_URL"],  # 예: http://localhost:11434/v1
        )
        resp = client.chat.completions.create(
            model=os.environ["LLM_MODEL"],
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content

    else:
        # 기본값: OpenAI
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            max_tokens=2000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": QUIZ_PROMPT_KO}],
        )
        return resp.choices[0].message.content


quiz_json_str = call_llm(QUIZ_PROMPT_KO)
quiz = json.loads(quiz_json_str)

# 객관식 먼저, 서술형 나중
mc = [q for q in quiz["questions"] if q["type"] == "multiple"]
essay = [q for q in quiz["questions"] if q["type"] == "essay"]
quiz["questions"] = mc + essay
quiz["draftFile"] = DRAFT_FILE
quiz["content"] = content[:2000]
quiz["userAnswers"] = {}

# ===== Queue Management =====

queue_raw = get_kv("PENDING_QUEUE")
queue = json.loads(queue_raw) if queue_raw else []

if len(queue) >= QUEUE_MAX:
    send_telegram(
        f"⚠️ 큐가 꽉 찼습니다 ({QUEUE_MAX}개)\n"
        f"기존 글이 발행된 후 다시 push해주세요\n\n"
        f"미등록: _{quiz['title']}_"
    )
    raise SystemExit(0)

slug = hashlib.md5(DRAFT_FILE.encode()).hexdigest()[:8]
quiz_key = f"pending_quiz_{slug}"
put_kv(quiz_key, json.dumps(quiz, ensure_ascii=True), expiration_ttl=7 * 86400)

queue.append({"file": DRAFT_FILE, "title": quiz["title"], "quizKey": quiz_key})
put_kv("PENDING_QUEUE", json.dumps(queue, ensure_ascii=True))

existing_date = get_kv("NEXT_QUIZ_DATE")
if not existing_date:
    today_kst = (datetime.now(timezone.utc) + timedelta(hours=9)).strftime("%Y-%m-%d")
    put_kv("NEXT_QUIZ_DATE", today_kst)

quiz_date = get_kv("NEXT_QUIZ_DATE")
source_line = f"소스: `{SOURCE_FILE}`\n" if SOURCE_FILE else ""

send_telegram(
    f"📥 *퀴즈 등록됐습니다*\n\n"
    f"제목: _{quiz['title']}_\n"
    f"{source_line}"
    f"퀴즈 예정: {quiz_date} 18:00 KST"
)
