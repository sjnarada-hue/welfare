"""Reply → 카카오 i 오픈빌더 스킬 응답(JSON v2.0) 변환.

참고: https://kakaobusiness.gitbook.io/main/tool/chatbot/skill_guide/answer_json_format
"""

from __future__ import annotations

from .bot import Reply
from .knowledge import Knowledge

SIMPLE_TEXT_MAX = 1000
LABEL_MAX = 14  # 바로가기 응답(quickReplies) 버튼 글자 수 제한
MAX_OUTPUTS = 3


def _split(text: str, size: int = SIMPLE_TEXT_MAX) -> list[str]:
    chunks, buf = [], ""
    for line in text.split("\n"):
        while len(line) > size:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.append(line[:size])
            line = line[size:]
        candidate = f"{buf}\n{line}" if buf else line
        if len(candidate) > size:
            chunks.append(buf)
            buf = line
        else:
            buf = candidate
    if buf:
        chunks.append(buf)
    return chunks or [""]


def _quick_reply(text: str) -> dict:
    label = text if len(text) <= LABEL_MAX else text[: LABEL_MAX - 1] + "…"
    return {"label": label, "action": "message", "messageText": text}


def _menu_card(knowledge: Knowledge) -> dict:
    # listCard: 큰 글씨 목록 버튼. 항목은 최대 5개.
    items = [
        {"title": item.message, "action": "message", "messageText": item.message}
        for item in knowledge.menu[:5]
    ]
    return {"listCard": {"header": {"title": "무엇을 도와드릴까요?"}, "items": items}}


def to_template(reply: Reply, knowledge: Knowledge) -> dict:
    outputs: list[dict] = []
    reserved = int(reply.show_menu) + int(bool(reply.links) or reply.operator)
    for chunk in _split(reply.text)[: MAX_OUTPUTS - reserved]:
        outputs.append({"simpleText": {"text": chunk}})

    if reply.show_menu:
        outputs.append(_menu_card(knowledge))

    buttons: list[dict] = []
    if reply.operator:
        buttons.append({"label": "상담원 연결", "action": "operator"})
    for link in reply.links:
        buttons.append({"label": link.label[:LABEL_MAX], "action": "webLink", "webLinkUrl": link.url})
    if buttons:
        outputs.append({"textCard": {"title": "바로가기", "buttons": buttons[:3]}})

    template: dict = {"outputs": outputs}
    if reply.quick_replies:
        template["quickReplies"] = [_quick_reply(q) for q in reply.quick_replies[:10]]
    return template


def to_response(reply: Reply, knowledge: Knowledge) -> dict:
    return {"version": "2.0", "template": to_template(reply, knowledge)}


def callback_ack(text: str) -> dict:
    """AI 답변처럼 5초를 넘길 수 있는 경우: 먼저 '기다려 주세요'를 보내고 나중에 콜백으로 답한다."""
    return {"version": "2.0", "useCallback": True, "data": {"text": text}}


def parse_request(body: dict) -> tuple[str, str, str | None]:
    """(사용자ID, 발화, 콜백URL)"""
    user_request = body.get("userRequest", {}) or {}
    utterance = (user_request.get("utterance") or "").strip()
    user = user_request.get("user", {}) or {}
    user_id = user.get("id") or "anonymous"
    callback_url = user_request.get("callbackUrl")
    return user_id, utterance, callback_url
