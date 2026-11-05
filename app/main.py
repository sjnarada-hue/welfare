"""웹 서버.

- POST /kakao/skill : 카카오 i 오픈빌더 스킬 서버 주소로 등록한다.
- POST /api/chat    : 웹 데모(테스트 화면)용.
- GET  /            : 카카오톡처럼 생긴 테스트 화면. 카카오 연결 전에 학과에서 미리 써 볼 수 있다.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import kakao
from .bot import Bot, Reply
from .knowledge import Knowledge

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger("welfare-bot")

STATIC = Path(__file__).resolve().parent / "static"
# 콜백을 쓰지 않는 블록에서 AI 답을 기다릴 최대 시간(카카오 제한 5초).
SYNC_AI_TIMEOUT = float(os.getenv("SYNC_AI_TIMEOUT", "4.0"))
# 오픈빌더 스킬 설정의 '헤더 값'과 같게 맞추면 다른 곳에서 오는 요청을 막을 수 있다(선택).
SKILL_TOKEN = os.getenv("KAKAO_SKILL_TOKEN", "")

app = FastAPI(title="학과 카카오톡 챗봇")
bot = Bot(Knowledge.load(os.getenv("KNOWLEDGE_PATH")))


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ai": bot.ai.enabled}


# ---------------- 카카오 ----------------
def _send_callback(url: str, user_id: str, utterance: str) -> None:
    reply = bot.respond(user_id, utterance)
    payload = kakao.to_response(reply, bot.knowledge)
    try:
        httpx.post(url, json=payload, timeout=10.0).raise_for_status()
    except httpx.HTTPError as e:
        log.error("카카오 콜백 전송 실패: %s", e)


@app.post("/kakao/skill")
async def kakao_skill(
    request: Request,
    background: BackgroundTasks,
    x_skill_token: str | None = Header(default=None),
) -> dict:
    if SKILL_TOKEN and x_skill_token != SKILL_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")
    body = await request.json()
    user_id, utterance, callback_url = kakao.parse_request(body)
    log.info("kakao user=%s… len=%d callback=%s", user_id[:6], len(utterance), bool(callback_url))

    if bot.needs_ai(utterance):
        if callback_url:
            background.add_task(_send_callback, callback_url, user_id, utterance)
            return kakao.callback_ack(bot.thinking_text())
        try:
            reply = await asyncio.wait_for(
                asyncio.to_thread(bot.respond, user_id, utterance), timeout=SYNC_AI_TIMEOUT
            )
        except asyncio.TimeoutError:
            reply = Reply(
                text=(
                    "답을 찾는 데 시간이 오래 걸리고 있어요.\n"
                    "잠시 후 다시 물어봐 주시거나, 교수님·조교께 직접 물어봐 주세요."
                ),
                quick_replies=["교수님(조교)께 직접 물어보기", "처음으로"],
                source="fallback",
            )
        return kakao.to_response(reply, bot.knowledge)

    return kakao.to_response(bot.respond(user_id, utterance), bot.knowledge)


# ---------------- 웹 데모 ----------------
class ChatIn(BaseModel):
    session_id: str
    message: str


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict:
    reply = await asyncio.to_thread(bot.respond, f"web:{body.session_id}", body.message[:1000])
    return {
        "text": reply.text,
        "links": [{"label": l.label, "url": l.url} for l in reply.links],
        "quick_replies": reply.quick_replies,
        "menu": [m.message for m in bot.knowledge.menu] if reply.show_menu else [],
        "operator": reply.operator,
        "source": reply.source,
    }


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")
