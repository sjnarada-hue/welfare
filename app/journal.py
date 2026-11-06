"""실습일지 도우미: 오늘 한 일 메모를 사회복지 현장실습 일지 초안으로 바꾼다.

- 학생 메모는 저장하지 않는다. 초안은 학생 휴대폰(브라우저)에만 저장된다.
- 이용자 실명은 쓰지 않고 'A 어르신', 'B 아동'처럼 기호로 바꿔 쓰게 한다.
- 주민번호·비밀번호처럼 보이는 내용이 있으면 AI로 보내지 않는다.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import anthropic

from . import privacy

log = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
# 일지 문장은 짧고 형식이 정해져 있어 low로도 충분하다. 필요하면 환경변수로 올린다.
EFFORT = os.getenv("JOURNAL_EFFORT", "low")

SYSTEM = """당신은 사회복지 현장실습생의 실습일지 초안을 써 주는 도우미입니다.
학생은 야간에 공부하는 성인학습자이며, 그날 한 일을 짧은 메모나 말로 남깁니다.
메모를 바탕으로 학교에 제출하는 실습일지의 세 칸을 채웁니다.

칸별 작성법
- 실습내용: 그날 한 일을 시간 순서(오전·오후 등)로, 사실만 씁니다. 3~6문장.
  메모에 없는 활동, 숫자, 장소, 프로그램 이름은 절대 지어내지 않습니다.
- 실습소감: '기억에 남는 순간'이 있으면 그 장면을 중심으로, 느끼고 배운 점을 씁니다. 3~5문장.
  없으면 메모에 적힌 활동에서 배운 점을 담담하게 씁니다. 과장된 감탄이나 상투적인 다짐은 피합니다.
- 의견 및 질문: 실습지도자(슈퍼바이저)에게 묻고 싶은 점이나 더 알아보고 싶은 점을 1~3문장으로 씁니다.
  사회복지 실천의 관점(이용자 중심, 강점 관점, 자기결정권, 비밀보장, 지역사회 자원 연계 등)이 자연스럽게 드러나면 좋습니다.

문체
- 실습일지 문체인 '~하였다', '~느꼈다'체로 씁니다. 마크다운 기호(#, *, -, 표)는 쓰지 않습니다.
- 학생이 쓴 사실을 바꾸지 않습니다. 메모가 짧으면 초안도 짧게 씁니다.

개인정보
- 이용자(어르신, 아동, 장애인, 가족 등)의 실명은 절대 쓰지 않습니다.
  메모에 이름이 나오면 등장 순서대로 'A 어르신', 'B 아동', 'C 이용자'처럼 기호로 바꿉니다.
  '김OO'처럼 성만 남기는 것도 쓰지 않습니다.
- 주소, 전화번호, 병명 같은 민감한 세부사항은 일지에 꼭 필요한 정도로만 일반화해서 씁니다.
- 기관 직원 이름도 쓰지 않고 '실습지도자', '담당 사회복지사'처럼 역할로 씁니다.
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "content": {"type": "string", "description": "실습내용"},
        "reflection": {"type": "string", "description": "실습소감"},
        "questions": {"type": "string", "description": "의견 및 질문"},
    },
    "required": ["content", "reflection", "questions"],
    "additionalProperties": False,
}

PRIVACY_MESSAGE = (
    "주민등록번호·비밀번호·학번처럼 보이는 내용이 있어 일지를 만들지 않았어요. "
    "그 부분을 지우고 다시 눌러 주세요."
)


@dataclass
class JournalInput:
    date: str
    day: str
    agency: str
    activities: str
    moment: str = ""


class JournalError(Exception):
    """학생에게 그대로 보여 줄 수 있는 안내 문구를 담는다."""


class JournalWriter:
    def __init__(self, client: anthropic.Anthropic | None = None):
        self._client = client

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(
            os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        )

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            self._client = anthropic.Anthropic(timeout=50.0, max_retries=1)
        return self._client

    @staticmethod
    def build_prompt(j: JournalInput) -> str:
        lines = [
            f"실습 날짜: {j.date or '(없음)'}",
            f"실습 일차: {j.day or '(없음)'}",
            f"실습기관: {j.agency or '(없음)'}",
            "",
            "[오늘 한 일 메모]",
            j.activities.strip(),
            "",
            "[기억에 남는 순간]",
            j.moment.strip() or "(적지 않음)",
        ]
        return "\n".join(lines)

    def write(self, j: JournalInput) -> dict:
        if not j.activities.strip():
            raise JournalError("오늘 한 일을 한 가지 이상 적어 주세요.")
        if privacy.contains_sensitive(f"{j.activities}\n{j.moment}"):
            raise JournalError(PRIVACY_MESSAGE)
        if not self.enabled:
            raise JournalError("지금은 일지 만들기를 쓸 수 없어요. 학과 조교에게 알려 주세요.")

        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=4000,
                system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": self.build_prompt(j)}],
                output_config={
                    "effort": EFFORT,
                    "format": {"type": "json_schema", "schema": SCHEMA},
                },
                # 안전 분류기가 드물게 일반 요청을 거절할 때 다른 모델로 다시 쓰게 한다.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as e:
            log.warning("Claude 연결 실패: %s", e)
            raise JournalError("연결이 잠시 불안정해요. 조금 뒤 다시 눌러 주세요.") from e
        except anthropic.RateLimitError as e:
            log.warning("Claude 사용량 한도 초과: %s", e)
            raise JournalError("지금 사용하는 사람이 많아요. 1분쯤 뒤 다시 눌러 주세요.") from e
        except anthropic.APIStatusError as e:
            log.error("Claude API 오류 %s: %s", e.status_code, e.message)
            raise JournalError("일지를 만들지 못했어요. 잠시 후 다시 시도해 주세요.") from e

        if response.stop_reason == "refusal":
            raise JournalError("이 메모로는 일지를 만들지 못했어요. 내용을 조금 바꿔 다시 시도해 주세요.")
        if response.stop_reason == "max_tokens":
            raise JournalError("메모가 너무 길어요. 조금 줄여서 다시 시도해 주세요.")

        text = next((b.text for b in response.content if b.type == "text"), "")
        try:
            data = json.loads(text)
            return {k: str(data[k]).strip() for k in ("content", "reflection", "questions")}
        except (ValueError, KeyError, TypeError) as e:
            log.error("일지 응답 형식 오류: %r", text[:200])
            raise JournalError("일지를 만들지 못했어요. 다시 한 번 눌러 주세요.") from e
