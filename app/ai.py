"""버튼에 없는 질문을 Claude가 학과 자료만 근거로 답하게 한다."""

from __future__ import annotations

import logging
import os

import anthropic

from .knowledge import Knowledge

log = logging.getLogger(__name__)

MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
# 짧은 안내 답변이라 응답 속도를 위해 low로 둔다. 필요하면 환경변수로 올린다.
EFFORT = os.getenv("CLAUDE_EFFORT", "low")

# AI가 이 문구를 답에 넣으면 '사람 연결' 버튼을 함께 보여 준다.
HANDOFF_MARK = "[연결필요]"

SYSTEM_TEMPLATE = """당신은 {school} {dept} 학생을 돕는 카카오톡 채널 도우미입니다.
학생들은 모두 야간에 공부하는 성인학습자이고, 컴퓨터와 스마트폰이 익숙하지 않은 분이 많습니다.

답변 원칙
- 존댓말로, 쉬운 우리말로 씁니다. 영어·전문용어는 꼭 필요할 때만 쓰고 바로 풀어서 설명합니다.
- 해야 할 일은 1. 2. 3. 번호를 붙여 한 줄에 한 동작씩 씁니다. 버튼 이름은 '로그인'처럼 따옴표로 표시합니다.
- 카카오톡 말풍선에 들어가도록 400자 안쪽으로 짧게 씁니다. 마크다운 기호(#, **, 표)는 쓰지 않습니다.
- 휴대폰 기종이나 앱 화면이 사람마다 다를 수 있으니, 화면이 다르면 비슷한 이름의 메뉴를 찾아보라고 덧붙입니다.

정확성
- 학교·학과에 관한 사실(주소, 메뉴 경로, 연락처, 기한, 규정)은 아래 [학과 자료]에 있는 것만 말합니다.
  자료에 없으면 추측하지 말고 "정확한 내용은 확인이 필요해요"라고 말한 뒤 교수님·조교 연결을 권합니다.
- 줌·팀즈·카카오톡·스마트폰 사용법 같은 일반적인 사용법은 일반 지식으로 안내해도 됩니다.
- 대괄호로 된 값(예: [조교 이름])은 아직 정해지지 않은 정보이므로 그대로 말하지 말고 확인이 필요하다고 합니다.

안전
- 학번, 비밀번호, 주민등록번호를 절대 묻거나 채팅에 쓰라고 하지 않습니다.
- 비밀번호 분실, 계정 잠김은 챗봇이 해결할 수 없으니 전산 담당 부서로 안내합니다.

사람 연결
- 자료로 답할 수 없거나, 학생이 사람과 이야기하길 원하거나, 성적·장학·휴학처럼 개인 사정이 걸린 문제라면
  답변 맨 끝에 {mark} 라고 정확히 적습니다. 그러면 교수님·조교 연락처 버튼이 함께 나갑니다.

[학과 자료]
{reference}
"""


class AIAnswerer:
    def __init__(self, knowledge: Knowledge, client: anthropic.Anthropic | None = None):
        self.knowledge = knowledge
        self._client = client
        d = knowledge.department
        self.system = SYSTEM_TEMPLATE.format(
            school=d.get("school_name", ""),
            dept=d.get("department_name", ""),
            mark=HANDOFF_MARK,
            reference=knowledge.as_reference_text(),
        )

    @property
    def enabled(self) -> bool:
        return self._client is not None or bool(
            os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        )

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # 카카오 콜백 제한(1분) 안에 끝나도록 타임아웃을 짧게 둔다.
            self._client = anthropic.Anthropic(timeout=40.0, max_retries=1)
        return self._client

    def answer(self, history: list[dict], question: str) -> tuple[str, bool] | None:
        """(답변, 사람연결필요) 를 돌려준다. 실패하면 None."""
        messages = [*history, {"role": "user", "content": question}]
        try:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=2000,
                # 학과 자료가 담긴 시스템 프롬프트는 매번 같으므로 캐시해 비용을 줄인다.
                system=[{"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}],
                messages=messages,
                output_config={"effort": EFFORT},
                # 안전 분류기가 드물게 일반 질문을 거절할 때 다른 모델로 다시 답하게 한다.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
        except anthropic.APIConnectionError as e:
            log.warning("Claude 연결 실패: %s", e)
            return None
        except anthropic.RateLimitError as e:
            log.warning("Claude 사용량 한도 초과: %s", e)
            return None
        except anthropic.APIStatusError as e:
            log.error("Claude API 오류 %s: %s", e.status_code, e.message)
            return None

        if response.stop_reason == "refusal":
            return None

        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if not text:
            return None
        handoff = HANDOFF_MARK in text
        text = text.replace(HANDOFF_MARK, "").strip()
        return text, handoff
