from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import kakao, privacy
from app.ai import AIAnswerer, HANDOFF_MARK
from app.bot import Bot
from app.knowledge import Knowledge


class FakeMessages:
    def __init__(self, text="1. 설정을 여세요.", stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text=self.text)],
        )


def make_bot(text="1. 설정을 여세요.", stop_reason="end_turn"):
    knowledge = Knowledge.load()
    messages = FakeMessages(text, stop_reason)
    client = SimpleNamespace(beta=SimpleNamespace(messages=messages))
    return Bot(knowledge, AIAnswerer(knowledge, client=client)), messages


def test_welcome_shows_menu():
    bot, _ = make_bot()
    r = bot.respond("u", "처음으로")
    assert r.show_menu


@pytest.mark.parametrize(
    "utterance,expected",
    [
        ("학교 홈페이지 로그인이 안 돼요", "login"),
        ("줌 어떻게 들어가요", "zoom_teams"),
        ("과제 제출", "assignment"),
        ("비번 까먹었어요", "password"),
    ],
)
def test_menu_matching(utterance, expected):
    assert Knowledge.load().match(utterance).id == expected


def test_button_answer_does_not_call_ai():
    bot, messages = make_bot()
    r = bot.respond("u", "과제는 어디에 내요?")
    assert r.source == "menu" and r.links
    assert messages.calls == []


def test_handoff_button():
    bot, _ = make_bot()
    r = bot.respond("u", "교수님(조교)께 직접 물어보기")
    assert r.source == "handoff" and r.operator


def test_free_question_goes_to_ai_with_reference():
    bot, messages = make_bot()
    r = bot.respond("u", "수업 중에 카메라를 켜야 하는데 화면이 까맣게 나와요 어떻게 하나요")
    assert r.source == "ai"
    call = messages.calls[0]
    assert "과제는 어디에 내요?" in call["system"][0]["text"]
    assert call["fallbacks"] == "default"


def test_ai_handoff_mark_adds_contacts():
    bot, _ = make_bot(text=f"확인이 필요해요. {HANDOFF_MARK}")
    r = bot.respond("u", "이번 학기 장학금 신청 기간이 언제인지 알려주실 수 있나요")
    assert HANDOFF_MARK not in r.text and r.operator


def test_refusal_falls_back_to_human():
    bot, _ = make_bot(stop_reason="refusal")
    r = bot.respond("u", "이번 학기 장학금 신청 기간이 언제인지 알려주실 수 있나요")
    assert r.source == "fallback"


@pytest.mark.parametrize("text", ["학번 20231234 인데요", "비밀번호는 abc12345!", "900101-1234567"])
def test_sensitive_info_never_reaches_ai(text):
    bot, messages = make_bot()
    r = bot.respond("u", text)
    assert r.source == "privacy" and messages.calls == []
    assert privacy.contains_sensitive(text)


def test_password_question_is_not_flagged():
    assert not privacy.contains_sensitive("비밀번호를 잊어버렸어요")


def test_kakao_response_shape():
    bot, _ = make_bot()
    out = kakao.to_response(bot.respond("u", "처음으로"), bot.knowledge)
    assert out["version"] == "2.0"
    kinds = [list(o)[0] for o in out["template"]["outputs"]]
    assert kinds == ["simpleText", "listCard"]
    assert len(out["template"]["outputs"][1]["listCard"]["items"]) <= 5


def test_kakao_quick_reply_label_limit():
    bot, _ = make_bot()
    out = kakao.to_response(bot.respond("u", "아무거나"), bot.knowledge)
    for q in out["template"].get("quickReplies", []):
        assert len(q["label"]) <= kakao.LABEL_MAX


def test_long_text_is_split():
    chunks = kakao._split("가" * 2500)
    assert len(chunks) == 3 and all(len(c) <= 1000 for c in chunks)


def test_kakao_endpoint_uses_callback_for_ai(monkeypatch):
    from app import main

    bot, _ = make_bot()
    monkeypatch.setattr(main, "bot", bot)
    sent = []
    monkeypatch.setattr(main.httpx, "post", lambda url, json, timeout: sent.append(json) or SimpleNamespace(raise_for_status=lambda: None))
    client = TestClient(main.app)
    body = {"userRequest": {"utterance": "카메라가 안 켜져요 수업 중인데 어떻게 해야 하나요", "user": {"id": "abc"}, "callbackUrl": "https://cb.example"}}
    res = client.post("/kakao/skill", json=body).json()
    assert res["useCallback"] is True
    assert sent and sent[0]["template"]["outputs"][0]["simpleText"]["text"]


def test_kakao_endpoint_menu_is_immediate():
    from app import main

    client = TestClient(main.app)
    body = {"userRequest": {"utterance": "과제는 어디에 내요?", "user": {"id": "abc"}}}
    res = client.post("/kakao/skill", json=body).json()
    assert "template" in res
