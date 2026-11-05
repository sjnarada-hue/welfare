"""학번·비밀번호·주민번호 같은 개인정보가 채팅에 들어왔는지 살핀다.

들어온 경우 AI에 보내지 않고, 저장하지 않으며, 주의 안내만 돌려준다.
"""

from __future__ import annotations

import re

_PATTERNS = [
    # 주민등록번호
    re.compile(r"\d{6}\s*-\s*[1-4]\d{6}"),
    # '비밀번호/비번/pw' 뒤에 실제 값처럼 보이는 문자열이 붙은 경우
    re.compile(r"(비밀\s*번호|비번|패스워드|password|pw)\s*(은|는|:|=)?\s*[A-Za-z0-9!@#$%^&*_\-+=]{4,}", re.I),
    # '학번' 뒤에 숫자가 붙은 경우
    re.compile(r"학번\s*(은|는|:|=)?\s*\d{6,10}"),
    # 학번처럼 보이는 8~10자리 숫자 단독
    re.compile(r"(?<!\d)(19|20)\d{6,8}(?!\d)"),
]

WARNING_TEXT = (
    "⚠️ 잠깐만요!\n"
    "학번, 비밀번호, 주민등록번호 같은 개인정보는 채팅창에 쓰지 말아 주세요.\n"
    "방금 보낸 메시지는 저장하거나 AI에게 보내지 않았어요.\n\n"
    "개인정보 없이 어떤 부분이 막혔는지만 다시 알려 주시면 도와드릴게요."
)


def contains_sensitive(text: str) -> bool:
    return any(p.search(text) for p in _PATTERNS)
