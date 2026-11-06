import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.journal import JournalError, JournalInput, JournalWriter

DRAFT = {"content": "오전에는 경로당을 방문하였다.", "reflection": "A 어르신과 이야기하였다.", "questions": "프로그램이 궁금하다."}


class FakeMessages:
    def __init__(self, text=json.dumps(DRAFT, ensure_ascii=False), stop_reason="end_turn"):
        self.text, self.stop_reason, self.calls = text, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=self.text)])


def make_writer(**kw):
    messages = FakeMessages(**kw)
    return JournalWriter(client=SimpleNamespace(beta=SimpleNamespace(messages=messages))), messages


def entry(**kw):
    base = dict(date="2026-11-06", day="3", agency="○○복지관", activities="경로당 혈압측정 도움", moment="")
    return JournalInput(**{**base, **kw})


def test_writes_draft_with_schema_and_memo():
    w, m = make_writer()
    assert w.write(entry(moment="할머니가 말벗이 없다고 함")) == DRAFT
    call = m.calls[0]
    assert call["output_config"]["format"]["type"] == "json_schema"
    prompt = call["messages"][0]["content"]
    assert "경로당 혈압측정 도움" in prompt and "말벗" in prompt and "○○복지관" in prompt


def test_empty_activities_rejected_without_calling_ai():
    w, m = make_writer()
    with pytest.raises(JournalError, match="한 가지 이상"):
        w.write(entry(activities="   "))
    assert not m.calls


def test_sensitive_info_not_sent():
    w, m = make_writer()
    with pytest.raises(JournalError, match="주민등록번호"):
        w.write(entry(moment="어르신 주민번호 450101-2345678 확인"))
    assert not m.calls


@pytest.mark.parametrize("kw", [{"stop_reason": "refusal"}, {"stop_reason": "max_tokens"}, {"text": "not json"}])
def test_bad_responses_become_friendly_errors(kw):
    w, _ = make_writer(**kw)
    with pytest.raises(JournalError):
        w.write(entry())


def test_api_endpoint(monkeypatch):
    w, _ = make_writer()
    monkeypatch.setattr(main, "journal", w)
    client = TestClient(main.app)
    r = client.post("/api/journal", json={"date": "2026-11-06", "day": "3", "agency": "", "activities": "사례회의 참관"})
    assert r.status_code == 200 and r.json() == DRAFT
    r = client.post("/api/journal", json={"activities": ""})
    assert r.status_code == 422 and "한 가지 이상" in r.json()["error"]


def test_journal_page_and_manifest():
    client = TestClient(main.app)
    page = client.get("/journal")
    assert page.status_code == 200 and "실습일지 도우미" in page.text
    mf = client.get("/journal.webmanifest").json()
    assert mf["start_url"] == "/journal"
