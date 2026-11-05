"""챗봇의 핵심 흐름: 버튼 → AI → 사람.

앱 화면은 Reply 객체를 받아 말풍선·버튼·연락처 카드로 그린다.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field

from . import privacy
from .ai import AIAnswerer
from .knowledge import Knowledge, Link, MenuItem

HOME = "처음으로"
SOLVED = "해결됐어요"
NOT_SOLVED = "해결 안 됐어요"
HOME_WORDS = {"처음으로", "처음", "메뉴", "시작", "홈", "도움말", "안녕", "안녕하세요"}


@dataclass
class Reply:
    text: str
    links: list[Link] = field(default_factory=list)
    # 글을 쓰지 않고 누를 수 있는 버튼(누르면 그 문장이 그대로 전송됨)
    quick_replies: list[str] = field(default_factory=list)
    # True면 첫 화면 큰 버튼 메뉴를 보여 준다.
    show_menu: bool = False
    # True면 교수·조교 연락처 카드(전화·이메일 버튼)를 함께 보여 준다.
    show_contacts: bool = False
    source: str = "menu"  # menu | ai | handoff | privacy | fallback


class History:
    """사용자별 최근 대화 몇 턴만 메모리에 잠깐 보관한다(후속 질문 이해용)."""

    def __init__(self, max_users: int = 1000, max_turns: int = 6, ttl_seconds: int = 1800):
        self._data: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()
        self.max_users, self.max_turns, self.ttl = max_users, max_turns, ttl_seconds

    def get(self, user_id: str) -> list[dict]:
        item = self._data.get(user_id)
        if not item or time.time() - item[0] > self.ttl:
            self._data.pop(user_id, None)
            return []
        return list(item[1])

    def add(self, user_id: str, question: str, answer: str) -> None:
        turns = self.get(user_id) + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        self._data[user_id] = (time.time(), turns[-self.max_turns * 2 :])
        self._data.move_to_end(user_id)
        while len(self._data) > self.max_users:
            self._data.popitem(last=False)

    def clear(self, user_id: str) -> None:
        self._data.pop(user_id, None)


class Bot:
    def __init__(self, knowledge: Knowledge, ai: AIAnswerer | None = None):
        self.knowledge = knowledge
        self.ai = ai if ai is not None else AIAnswerer(knowledge)
        self.history = History()

    # ---- 고정 화면 ----
    def welcome(self) -> Reply:
        d = self.knowledge.department
        return Reply(
            text=(
                f"안녕하세요! {d.get('department_name', '학과')} 도우미예요 😊\n"
                "아래 버튼 중 하나를 눌러 보세요.\n"
                "버튼에 없는 내용은 채팅창에 편하게 물어보셔도 돼요.\n\n"
                "※ 학번·비밀번호는 절대 쓰지 마세요."
            ),
            show_menu=True,
        )

    def handoff(self) -> Reply:
        return Reply(
            text=(
                "교수님·조교에게 직접 물어보실 수 있어요.\n"
                "아래 '전화하기'나 '이메일 보내기'를 누르세요.\n\n"
                "※ 연락할 때는 이름과 과목, 어디서 막혔는지만 알려 주세요.\n"
                "비밀번호는 절대 알려 주지 마세요."
            ),
            quick_replies=[HOME],
            show_contacts=True,
            source="handoff",
        )

    def _menu_reply(self, item: MenuItem) -> Reply:
        if item.handoff:
            return self.handoff()
        return Reply(
            text=item.answer,
            links=item.links,
            quick_replies=[SOLVED, NOT_SOLVED, HOME],
            source="menu",
        )

    # ---- 흐름 ----
    def respond(self, user_id: str, utterance: str) -> Reply:
        u = utterance.strip()

        if not u or u in HOME_WORDS:
            self.history.clear(user_id)
            return self.welcome()

        if privacy.contains_sensitive(u):
            return Reply(text=privacy.WARNING_TEXT, quick_replies=[HOME], source="privacy")

        if u == SOLVED:
            self.history.clear(user_id)
            return Reply(text="다행이에요! 또 막히면 언제든 이 채팅방에서 물어보세요 🙂", quick_replies=[HOME])

        if u == NOT_SOLVED:
            return self.handoff()

        # 1단계: 버튼(정해진 답)
        item = self.knowledge.match(u)
        if item:
            return self._menu_reply(item)

        # 2단계: AI
        if self.ai.enabled:
            result = self.ai.answer(self.history.get(user_id), u)
            if result:
                text, handoff = result
                self.history.add(user_id, u, text)
                if handoff:
                    return Reply(text=text, quick_replies=[HOME], show_contacts=True, source="ai")
                return Reply(text=text, quick_replies=[SOLVED, NOT_SOLVED, HOME], source="ai")

        # 3단계: 사람
        return Reply(
            text=(
                "죄송해요, 이 질문은 제가 정확히 답하기 어려워요.\n"
                "아래 버튼을 누르시거나, 교수님·조교께 직접 물어봐 주세요."
            ),
            quick_replies=["교수님(조교)께 직접 물어보기", HOME],
            source="fallback",
        )
