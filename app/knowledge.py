"""학과 지식 파일(data/knowledge.json)을 읽고, 질문을 메뉴 항목에 맞춰 찾는다."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "data" / "knowledge.json"


@dataclass
class Link:
    label: str
    url: str


@dataclass
class MenuItem:
    id: str
    label: str
    message: str
    keywords: list[str]
    answer: str = ""
    links: list[Link] = field(default_factory=list)
    handoff: bool = False


def _normalize(text: str) -> str:
    return re.sub(r"[\s?!.,~·()（）]", "", text).lower()


class Knowledge:
    def __init__(self, data: dict):
        self.raw = data
        self.department: dict = data.get("department", {})
        self.extra_faq: list[dict] = data.get("extra_faq", [])
        self.menu: list[MenuItem] = [self._build_item(m) for m in data.get("menu", [])]

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Knowledge":
        with open(path or DEFAULT_PATH, encoding="utf-8") as f:
            return cls(json.load(f))

    def _fill(self, text: str) -> str:
        # 답변 안의 {it_helpdesk} 같은 자리표시를 학과 정보로 채운다.
        def repl(m: re.Match) -> str:
            value = self.department.get(m.group(1))
            return str(value) if isinstance(value, (str, int)) else m.group(0)

        return re.sub(r"\{(\w+)\}", repl, text)

    def _build_item(self, m: dict) -> MenuItem:
        links = []
        for link in m.get("links", []):
            url = link.get("url") or self.department.get(link.get("url_key", ""), "")
            if url:
                links.append(Link(label=link["label"], url=url))
        return MenuItem(
            id=m["id"],
            label=m["label"],
            message=m.get("message", m["label"]),
            keywords=m.get("keywords", []),
            answer=self._fill(m.get("answer", "")),
            links=links,
            handoff=bool(m.get("handoff", False)),
        )

    def get(self, item_id: str) -> MenuItem | None:
        return next((m for m in self.menu if m.id == item_id), None)

    def match(self, utterance: str) -> MenuItem | None:
        """버튼을 눌렀거나(정확히 일치) 짧은 질문에 핵심 단어가 있으면 해당 메뉴를 돌려준다.

        긴 문장은 버튼 답변보다 AI가 더 잘 답할 수 있으므로, 키워드 매칭은
        짧은 질문(공백 제외 25자 이하)에만 적용한다.
        """
        norm = _normalize(utterance)
        if not norm:
            return None
        for item in self.menu:
            if norm in (_normalize(item.label), _normalize(item.message)):
                return item
        if len(norm) > 25:
            return None
        best, best_score = None, 0
        for item in self.menu:
            score = sum(1 for kw in item.keywords if _normalize(kw) in norm)
            if score > best_score:
                best, best_score = item, score
        return best

    def contacts_text(self) -> str:
        lines = []
        for c in self.department.get("contacts", []):
            lines.append(
                f"■ {c.get('role', '')} {c.get('name', '')}\n"
                f"  ☎ {c.get('phone', '')}\n"
                f"  ✉ {c.get('email', '')}\n"
                f"  🕒 {c.get('hours', '')}"
            )
        return "\n\n".join(lines)

    def as_reference_text(self) -> str:
        """AI에게 줄 근거 자료. 이 내용 밖의 학교 정보는 지어내지 않도록 한다."""
        d = self.department
        parts = [
            f"학교: {d.get('school_name', '')}",
            f"학과: {d.get('department_name', '')}",
            f"학교 홈페이지: {d.get('homepage_url', '')}",
            f"포털: {d.get('portal_url', '')}",
            f"LMS: {d.get('lms_name', '')} {d.get('lms_url', '')}",
            f"전산 담당 부서: {d.get('it_helpdesk', '')}",
            "",
            "[연락처]",
            self.contacts_text(),
            "",
            "[자주 묻는 질문과 공식 답변]",
        ]
        for item in self.menu:
            if item.answer:
                parts.append(f"Q. {item.message}\nA. {item.answer}")
                for link in item.links:
                    parts.append(f"  - {link.label}: {link.url}")
        for faq in self.extra_faq:
            parts.append(f"Q. {faq['q']}\nA. {faq['a']}")
        return "\n".join(parts)
