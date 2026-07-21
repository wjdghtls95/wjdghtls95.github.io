import os
import json
import requests
from openai import OpenAI

DRAFT_FILE = os.environ["DRAFT_FILE"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
TELEGRAM_CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

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
    {{"type": "multiple", "difficulty": "easy", "q": "질문", "options": ["A. 선택지", "B. 선택지", "C. 선택지", "D. 선택지"], "answer": "A"}},
    {{"type": "essay", "difficulty": "hard", "q": "질문"}}
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

def send_telegram(text: str) -> None:
    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "Markdown"},
    )

send_telegram(f"📝 *퀴즈 시작: {quiz['title']}*\n\n글을 잘 읽었나요? 10문제 시작합니다.\n답변 형식: 객관식은 A/B/C/D, 서술형은 자유롭게")

for i, q in enumerate(quiz["questions"], 1):
    if q["type"] == "multiple":
        opts = "\n".join(q["options"])
        send_telegram(f"*Q{i} [{q['difficulty']}] (객관식)*\n{q['q']}\n\n{opts}")
    else:
        send_telegram(f"*Q{i} [{q['difficulty']}] (서술형)*\n{q['q']}")

quiz["draft_file"] = DRAFT_FILE
with open("/tmp/quiz_session.json", "w", encoding="utf-8") as f:
    json.dump(quiz, f, ensure_ascii=False)

send_telegram("✍️ 답변을 순서대로 보내주세요. (Q1 → Q10)")
