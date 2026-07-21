import os
import json
import requests
from openai import OpenAI

DRAFT_FILE = os.environ["DRAFT_FILE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CF_ACCOUNT_ID = os.environ["CF_ACCOUNT_ID"]
CF_API_TOKEN = os.environ["CF_API_TOKEN"]
KV_NAMESPACE_ID = "36dfe08248484462b941e184e6e79c39"

with open(DRAFT_FILE, "r", encoding="utf-8") as f:
    content = f.read()

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

# 객관식 먼저, 서술형 나중으로 정렬
mc = [q for q in quiz["questions"] if q["type"] == "multiple"]
essay = [q for q in quiz["questions"] if q["type"] == "essay"]
quiz["questions"] = mc + essay

quiz["draftFile"] = DRAFT_FILE
quiz["content"] = content[:2000]
quiz["userAnswers"] = {}

# KV에 세션 저장
kv_url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/storage/kv/namespaces/{KV_NAMESPACE_ID}/values/{TELEGRAM_CHAT_ID}"
requests.put(
    kv_url,
    headers={"Authorization": f"Bearer {CF_API_TOKEN}"},
    data=json.dumps(quiz, ensure_ascii=False),
)

# 첫 번째 질문 전송
def send_telegram(text: str, reply_markup=None) -> None:
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json=payload,
    )

mc_questions = [q for q in quiz["questions"] if q["type"] == "multiple"]
mc_text = f"📝 *퀴즈 시작: {quiz['title']}*\n\n"

for i, q in enumerate(mc_questions):
    mc_text += f"*Q{i + 1} [{q['difficulty']}]*\n{q['q']}\n"
    for opt in q["options"]:
        mc_text += f"  {opt}\n"
    mc_text += "\n"

mc_text += "━━━━━━━━━━━━━━\n"
mc_text += f"📌 *{len(mc_questions)}글자로 답하세요* (예: `ABCDBCA`)"

send_telegram(mc_text)
