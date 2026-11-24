"""Persistent conversational memory with bounded context (spec §10).

A thread links successive research questions so a follow-up ("what would
invalidate that assessment?") understands what "that" refers to. Memory carries
*context hints only* — the securities discussed, the last assessment stance and
horizon, user-stated constraints — never the previous answer's conclusions as
though they were source evidence. Each new turn re-fetches and re-verifies;
freshness-sensitive facts are never reused on the strength of a prior turn.

Threads are persisted atomically under ``<state_dir>/threads/<thread_id>.json``
and bounded to the most recent turns so context stays compact (spec §12).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from strix.agent.models import MarketAssessment, ResearchResponse

#: Keep at most this many recent turns in a thread's working context.
MAX_CONTEXT_TURNS = 6
_THREAD_ID_RE = re.compile(r"^TH-[A-Za-z0-9]{1,40}$")


@dataclass(frozen=True)
class ConversationTurn:
    """One question/answer exchange, reduced to context-bearing fields."""

    run_id: str
    question: str
    intent: str
    direct_answer: str
    stance: str | None
    horizon: str | None
    securities: tuple[str, ...]
    created_at: str

    def to_json(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "question": self.question,
            "intent": self.intent,
            "direct_answer": self.direct_answer,
            "stance": self.stance,
            "horizon": self.horizon,
            "securities": list(self.securities),
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, data: dict[str, object]) -> ConversationTurn:
        raw_securities = data.get("securities")
        securities = (
            tuple(str(s) for s in raw_securities)
            if isinstance(raw_securities, list)
            else ()
        )
        return cls(
            run_id=str(data.get("run_id", "")),
            question=str(data.get("question", "")),
            intent=str(data.get("intent", "")),
            direct_answer=str(data.get("direct_answer", "")),
            stance=_opt_str(data.get("stance")),
            horizon=_opt_str(data.get("horizon")),
            securities=securities,
            created_at=str(data.get("created_at", "")),
        )


@dataclass(frozen=True)
class ThreadContext:
    """Compact prior-turn context handed to classification and synthesis."""

    has_prior: bool = False
    securities: tuple[str, ...] = ()
    last_stance: str | None = None
    last_horizon: str | None = None
    summary: str = ""

    @classmethod
    def empty(cls) -> ThreadContext:
        return cls()


@dataclass(frozen=True)
class ConversationThread:
    thread_id: str
    turns: tuple[ConversationTurn, ...] = ()

    def recent(self, limit: int = MAX_CONTEXT_TURNS) -> tuple[ConversationTurn, ...]:
        return self.turns[-limit:]

    def context(self) -> ThreadContext:
        """Build the bounded prior-turn context (securities, last stance/horizon)."""
        recent = self.recent()
        if not recent:
            return ThreadContext.empty()
        securities: list[str] = []
        for turn in recent:
            securities.extend(turn.securities)
        last = recent[-1]
        lines = [
            f"- {t.question!r} → {t.direct_answer[:160]}"
            + (f" [stance: {t.stance}]" if t.stance else "")
            for t in recent
        ]
        summary = "PRIOR CONVERSATION (context only — never cite as evidence):\n" + "\n".join(
            lines
        )
        return ThreadContext(
            has_prior=True,
            securities=tuple(dict.fromkeys(securities)),
            last_stance=last.stance,
            last_horizon=last.horizon,
            summary=summary,
        )

    def with_turn(self, turn: ConversationTurn) -> ConversationThread:
        return ConversationThread(thread_id=self.thread_id, turns=(*self.turns, turn))


class ThreadStore:
    """Atomic, bounded persistence for conversation threads."""

    def __init__(self, state_dir: Path) -> None:
        self._dir = Path(state_dir) / "threads"

    def load(self, thread_id: str) -> ConversationThread:
        _validate_id(thread_id)
        path = self._path(thread_id)
        if not path.exists():
            return ConversationThread(thread_id=thread_id)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            turns = tuple(ConversationTurn.from_json(t) for t in data.get("turns", []))
        except (OSError, ValueError):
            return ConversationThread(thread_id=thread_id)
        return ConversationThread(thread_id=thread_id, turns=turns)

    def append(self, thread_id: str, turn: ConversationTurn) -> ConversationThread:
        """Append a turn and persist, bounding stored history to a sane cap."""
        thread = self.load(thread_id).with_turn(turn)
        # Persist a bounded tail so a long thread never grows without limit.
        bounded = ConversationThread(
            thread_id=thread_id, turns=thread.turns[-(MAX_CONTEXT_TURNS * 4) :]
        )
        self._write(bounded)
        return thread

    def _write(self, thread: ConversationThread) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(thread.thread_id)
        tmp = path.with_suffix(".json.tmp")
        payload = {
            "thread_id": thread.thread_id,
            "turns": [t.to_json() for t in thread.turns],
        }
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)  # atomic within the same directory

    def _path(self, thread_id: str) -> Path:
        _validate_id(thread_id)
        return self._dir / f"{thread_id}.json"


def turn_from_response(
    response: ResearchResponse, *, securities: tuple[str, ...], now: datetime
) -> ConversationTurn:
    """Reduce a completed response to a storable conversation turn."""
    assessment: MarketAssessment | None = response.market_assessment
    return ConversationTurn(
        run_id=response.run_id,
        question=response.question,
        intent=response.question_intent,
        direct_answer=response.direct_answer,
        stance=assessment.stance.value if assessment is not None else None,
        horizon=assessment.horizon if assessment is not None else None,
        securities=securities,
        created_at=now.isoformat(),
    )


def _validate_id(thread_id: str) -> None:
    if not _THREAD_ID_RE.match(thread_id):
        raise ValueError(f"invalid thread id: {thread_id!r} (expected TH-<alnum>)")


def _opt_str(value: object) -> str | None:
    return str(value) if isinstance(value, str) and value else None
