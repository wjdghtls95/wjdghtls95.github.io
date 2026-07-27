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
# LLM_PROVIDER 명시 시 해당 프로바이더 사용
# 미설정 시 등록된 API 키로 자동 감지: anthropic → gemini → openai 순서
_explicit = os.environ.get("LLM_PROVIDER")
if _explicit:
    LLM_PROVIDER = _explicit
elif os.environ.get("ANTHROPIC_API_KEY"):
    LLM_PROVIDER = "anthropic"
elif os.environ.get("GEMINI_API_KEY"):
    LLM_PROVIDER = "gemini"
elif os.environ.get("OPENAI_API_KEY"):
    LLM_PROVIDER = "openai"
else:
    raise RuntimeError("LLM API 키가 하나도 설정되지 않았습니다. ANTHROPIC_API_KEY, GEMINI_API_KEY, OPENAI_API_KEY 중 하나를 설정하세요.")

with open(DRAFT_FILE, "r", encoding="utf-8") as f:
    content = f.read()

# frontmatter에서 source 파일 경로 파싱
import re as _re
_source_match = _re.search(r'^source:\s*(.+)$', content, _re.MULTILINE)
SOURCE_FILE = _source_match.group(1).strip() if _source_match else None

# 학습 위치 (옵시디언 파일 경로 또는 제목)
_study_match = _re.search(r'^study:\s*(.+)$', content, _re.MULTILINE)
STUDY_REF = _study_match.group(1).strip() if _study_match else None

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
    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {CF_API_TOKEN}", "Content-Type": "text/plain"},
        params=params,
        data=value_str.encode("utf-8"),
    )
    if not resp.ok:
        raise RuntimeError(f"KV 저장 실패 [{key}]: {resp.status_code} {resp.text}")

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
    """LLM_PROVIDER에 맞게 퀴즈 생성 요청. 모두 JSON 문자열 반환.
    지원 프로바이더: anthropic (기본) | gemini | openai
    """

    if LLM_PROVIDER == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        msg = client.messages.create(
            model=os.environ.get("LLM_MODEL") or "claude-haiku-4-5-20251001",
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return msg.content[0].text

    elif LLM_PROVIDER == "gemini":
        from google import genai
        client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        resp = client.models.generate_content(
            model=os.environ.get("LLM_MODEL") or "gemini-2.0-flash",
            contents=prompt,
        )
        return resp.text

    else:
        # 기본값: OpenAI
        from openai import OpenAI
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        resp = client.chat.completions.create(
            model=os.environ.get("LLM_MODEL") or "gpt-4o-mini",
            max_tokens=2000,
            response_format={"type": "json_object"},
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.choices[0].message.content


def extract_json(text: str) -> str:
    """LLM이 JSON을 마크다운 코드블록으로 감쌌을 경우 안쪽만 추출."""
    import re
    match = re.search(r'```(?:json)?\s*([\s\S]+?)\s*```', text)
    return match.group(1) if match else text.strip()

quiz_json_str = extract_json(call_llm(QUIZ_PROMPT_KO))
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
study_line = f"📚 공부할 곳: `{STUDY_REF}`\n" if STUDY_REF else ""

send_telegram(
    f"📥 *퀴즈 등록됐습니다*\n\n"
    f"제목: _{quiz['title']}_\n"
    f"{source_line}"
    f"{study_line}"
    f"퀴즈 예정: {quiz_date} 18:00 KST"
)
