"""학과 도우미 앱 서버.

- GET  /            : 챗봇 앱 화면 (폰 홈 화면에 추가해 앱처럼 쓴다)
- GET  /api/config  : 앱 이름·첫 화면 버튼 등 화면 설정
- POST /api/chat    : 질문을 받아 버튼 → AI → 사람 순서로 답한다
- GET  /journal     : 실습일지 도우미 앱 화면 (따로 홈 화면에 추가할 수 있다)
- POST /api/journal : 오늘 한 일 메모로 실습일지 초안을 만든다
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .bot import Bot
from .journal import JournalError, JournalInput, JournalWriter
from .knowledge import Knowledge

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

STATIC = Path(__file__).resolve().parent / "static"

app = FastAPI(title="학과 도우미")
bot = Bot(Knowledge.load(os.getenv("KNOWLEDGE_PATH")))
journal = JournalWriter()


@app.get("/health")
def health() -> dict:
    return {"ok": True, "ai": bot.ai.enabled, "journal": journal.enabled}


@app.get("/api/config")
def config() -> dict:
    d = bot.knowledge.department
    return {
        "app_name": d.get("app_name", "학과 도우미"),
        "school_name": d.get("school_name", ""),
        "department_name": d.get("department_name", ""),
        "ai": bot.ai.enabled,
    }


class ChatIn(BaseModel):
    session_id: str = Field(max_length=64)
    message: str = Field(max_length=1000)


@app.post("/api/chat")
async def chat(body: ChatIn) -> dict:
    reply = await asyncio.to_thread(bot.respond, body.session_id, body.message)
    return {
        "text": reply.text,
        "links": [{"label": l.label, "url": l.url} for l in reply.links],
        "quick_replies": reply.quick_replies,
        "menu": [m.message for m in bot.knowledge.menu] if reply.show_menu else [],
        "contacts": bot.knowledge.department.get("contacts", []) if reply.show_contacts else [],
        "source": reply.source,
    }


class JournalIn(BaseModel):
    date: str = Field(default="", max_length=20)
    day: str = Field(default="", max_length=10)
    agency: str = Field(default="", max_length=60)
    activities: str = Field(max_length=1500)
    moment: str = Field(default="", max_length=800)


@app.post("/api/journal")
async def write_journal(body: JournalIn):
    try:
        draft = await asyncio.to_thread(journal.write, JournalInput(**body.model_dump()))
    except JournalError as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return draft


@app.get("/journal")
def journal_page() -> FileResponse:
    return FileResponse(STATIC / "journal.html", headers={"Cache-Control": "no-cache"})


@app.get("/journal.webmanifest")
def journal_manifest() -> FileResponse:
    return FileResponse(STATIC / "journal.webmanifest", media_type="application/manifest+json")


# 서비스 워커는 앱 전체를 관리하려면 최상위 경로에서 내려가야 한다.
@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
def manifest() -> FileResponse:
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")
