"""Bounded research orchestration.

The single public entry point, :func:`run_research_question`, drives a bounded
tool-calling loop: the model plans and requests typed tools, each tool preserves
evidence / builds observation series / runs deterministic calculations, and the
model proposes candidate claims via ``submit_claim``. The model never sees or
sets a verdict. After the loop, the independent verifier recomputes every
quantitative claim from preserved observations; only VERIFIED claims become
findings, the rest are disclosed as unresolved. The answer is assembled
deterministically, validated fail-closed, and persisted replayably.

Budget (model calls, tool calls, tokens, wall-clock, USD) is enforced before
every call; on exhaustion the loop stops and returns partial verified findings.
Retrieved content is treated as untrusted data (the system prompt forbids
treating it as instructions); tool arguments are validated before execution.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from strix.agent import AGENT_VERSION
from strix.agent.budget import BudgetSnapshot, BudgetTracker
from strix.agent.citations import resolve_claim_citations
from strix.agent.conclusion_check import verify_final_answer
from strix.agent.config import AgentConfig, merged_environment
from strix.agent.connectors.market_data import AlpacaConnector
from strix.agent.evidence_collector import EvidenceCollector
from strix.agent.memory import ThreadContext
from strix.agent.models import (
    AgentClaim,
    AgentVerificationStatus,
    ResearchAnswer,
    ResearchResponse,
    SourceKind,
)
from strix.agent.openai_provider import OpenAIProvider
from strix.agent.persistence import persist_agent_run
from strix.agent.prompts import market_research_instructions
from strix.agent.question import classify_question
from strix.agent.response_builder import build_answer, build_response
from strix.agent.response_validator import validate_answer
from strix.agent.sanity import check_claims
from strix.agent.synthesis import synthesize
from strix.agent.tool_registry import ToolContext, ToolRegistry
from strix.agent.verifier import verify_claims
from strix.errors import BudgetExceededError

ProgressFn = Callable[[str], None]

#: Model calls held back from the research loop so synthesis always has budget.
SYNTHESIS_RESERVED_CALLS = 1


@dataclass(frozen=True)
class ResearchOutcome:
    answer: ResearchAnswer
    run_id: str
    run_dir: Path
    usage: BudgetSnapshot
    claims: tuple[AgentClaim, ...]
    response: ResearchResponse | None = None


def run_research_question(
    question: str,
    *,
    config: AgentConfig,
    state_dir: Path,
    provider: OpenAIProvider | None = None,
    alpaca: AlpacaConnector | None = None,
    registry: ToolRegistry | None = None,
    as_of: date | None = None,
    clock: Callable[[], datetime] | None = None,
    progress: ProgressFn | None = None,
    cancel_check: Callable[[], bool] | None = None,
    sec_fetch: Any = None,
    prior_context: ThreadContext | None = None,
) -> ResearchOutcome:
    """Research one question end-to-end and persist the run."""
    now_fn = clock or (lambda: datetime.now(UTC))
    now = now_fn()
    as_of = as_of or now.date()
    emit = progress or (lambda _m: None)
    prior_context = prior_context or ThreadContext.empty()

    provider = provider or OpenAIProvider(config)
    alpaca = alpaca or AlpacaConnector.from_env(merged_environment())
    registry = registry or ToolRegistry()
    collector = EvidenceCollector()
    budget = BudgetTracker(config)
    ctx = ToolContext(
        config=config,
        collector=collector,
        alpaca=alpaca,
        as_of=as_of,
        now=now,
        sec_fetch=sec_fetch,
    )

    research_question = classify_question(
        question, as_of=as_of, has_prior_context=prior_context.has_prior
    )

    tools = list(registry.function_schemas())
    if config.web_search_enabled:
        tools.append({"type": "web_search"})
    instructions = _system_instructions(as_of)

    # Reserve a model call for the final synthesis step (spec §12).
    max_loop_calls = max(1, config.max_model_calls - SYNTHESIS_RESERVED_CALLS)

    limitations: list[str] = []
    exhausted_reason = _run_loop(
        question=question,
        provider=provider,
        config=config,
        registry=registry,
        ctx=ctx,
        budget=budget,
        tools=tools,
        instructions=instructions,
        collector=collector,
        now=now,
        emit=emit,
        limitations=limitations,
        cancel_check=cancel_check,
        max_loop_calls=max_loop_calls,
    )

    emit("Resolving citations")
    resolution = resolve_claim_citations(tuple(ctx.candidate_claims), collector)
    if resolution.had_unresolved:
        dangling = sum(len(v) for v in resolution.dropped.values())
        limitations.append(
            f"{dangling} web-search citation(s) could not be resolved to a preserved "
            "source and were excluded; affected statements are shown as attributed, "
            "not independently verified."
        )

    emit("Independently verifying candidate claims")
    verified_all = verify_claims(resolution.claims, collector, now=now)
    verified = tuple(
        c for c in verified_all if c.verification.status is AgentVerificationStatus.VERIFIED
    )
    unresolved = tuple(
        c for c in verified_all if c.verification.status is not AgentVerificationStatus.VERIFIED
    )

    emit("Running data-quality sanity checks")
    sanity_flags = check_claims(verified, collector, as_of=as_of)
    for flag in sanity_flags:
        limitations.append(f"Data-quality check [{flag.code}]: {flag.message}")

    emit("Synthesizing analysis")
    draft = synthesize(
        question=research_question,
        verified=verified,
        unresolved=unresolved,
        collector=collector,
        sanity_flags=sanity_flags,
        as_of=as_of,
        now=now,
        provider=provider,
        budget=budget,
        config=config,
        prior_context=prior_context.summary or None,
    )
    limitations.extend(draft.limitations)

    # Independent conclusion-level verification of the COMPLETE final answer (DTEC A_C —
    # R∧K∧F). This runs on the authoritative chokepoint, so both CLI and webapi inherit it;
    # it is additive and never relaxes the per-claim verification above.
    emit("Independently verifying the final conclusion")
    conclusion_verification = verify_final_answer(
        proposition=draft.direct_answer, verified=verified, unresolved=unresolved
    )
    if conclusion_verification.outcome == "rejected":
        opposing = ", ".join(conclusion_verification.opposing_claim_ids)
        limitations.append(
            "Conclusion-level verification REJECTED the synthesized answer: the run contains "
            f"independently contradicted evidence ({opposing}); treat the conclusion as "
            "unverified at the conclusion level."
        )
    elif conclusion_verification.outcome == "abstained":
        limitations.append(
            "Conclusion-level verification ABSTAINED: no independently verified premise "
            "supports a conclusion for this question."
        )

    _collect_limitations(limitations, verified, unresolved, exhausted_reason, config)

    def make_answer(run_id: str) -> ResearchAnswer:
        return build_answer(
            run_id=run_id,
            question=question,
            verified_claims=verified,
            unresolved_claims=unresolved,
            collector=collector,
            limitations=tuple(dict.fromkeys(limitations)),
            now=now,
            conclusion_verification=conclusion_verification,
        )

    diagnostics = {
        "agent_version": AGENT_VERSION,
        "question_intent": research_question.intent.value,
        "forward_looking": str(research_question.is_forward_looking),
    }

    def make_response(run_id: str, answer: ResearchAnswer) -> ResearchResponse:
        return build_response(
            run_id=run_id,
            question=research_question,
            answer=answer,
            draft=draft,
            diagnostics=diagnostics,
        )

    # Fail closed: validate before persisting (placeholder id; id is not validated).
    validate_answer(make_answer("RUN-PENDING"), collector, config)

    emit("Persisting research artifacts")
    run_id, run_dir, answer, response = persist_agent_run(
        state_dir,
        question=question,
        as_of=as_of.isoformat(),
        config=config,
        collector=collector,
        claims=verified_all,
        make_answer=make_answer,
        make_response=make_response,
        usage=budget.snapshot(exhausted_reason=exhausted_reason),
        now=now,
    )
    return ResearchOutcome(
        answer=answer,
        run_id=run_id,
        run_dir=run_dir,
        usage=budget.snapshot(exhausted_reason=exhausted_reason),
        claims=verified_all,
        response=response,
    )


def _run_loop(
    *,
    question: str,
    provider: OpenAIProvider,
    config: AgentConfig,
    registry: ToolRegistry,
    ctx: ToolContext,
    budget: BudgetTracker,
    tools: list[dict[str, Any]],
    instructions: str,
    collector: EvidenceCollector,
    now: datetime,
    emit: ProgressFn,
    limitations: list[str],
    cancel_check: Callable[[], bool] | None = None,
    max_loop_calls: int | None = None,
) -> str | None:
    """Drive the bounded tool loop. Returns an exhaustion reason or None."""
    model_input: Any = [{"role": "user", "content": question}]
    previous_id: str | None = None
    loop_calls = max_loop_calls if max_loop_calls is not None else config.max_model_calls

    for step in range(loop_calls):
        if cancel_check is not None and cancel_check():
            return "cancelled by user"
        try:
            budget.ensure_can_call_model()
        except BudgetExceededError as exc:
            return str(exc)
        emit(f"Researching (model call {step + 1}/{loop_calls})")
        response = provider.create_response(
            input=model_input,
            instructions=instructions,
            tools=tools,
            previous_response_id=previous_id,
        )
        budget.record_model_call(response.usage)
        _register_web_citations(response, collector, now)

        if not response.tool_calls:
            return None  # model finished proposing

        outputs: list[dict[str, Any]] = []
        for call in response.tool_calls:
            try:
                budget.ensure_can_call_tool()
            except BudgetExceededError as exc:
                return str(exc)
            emit(f"Tool: {call.name}")
            result = registry.execute(call.name, call.arguments, ctx)
            budget.record_tool_call()
            if result.get("available") is False:
                _note_unavailable(limitations, result)
            outputs.append(
                {
                    "type": "function_call_output",
                    "call_id": call.call_id,
                    "output": json.dumps(result)[:8000],
                }
            )
        previous_id = response.response_id
        model_input = outputs

    return "model-call budget reached"


def _system_instructions(as_of: date) -> str:
    guide = (
        "\n\n## Operating context\n"
        f"- Today's date for research is {as_of.isoformat()}.\n"
        "- Work by calling tools. Fetch real data (get_historical_prices, "
        "get_sec_financials, get_market_quote), run numbers with `calculate`, and "
        "then record each finding with `submit_claim` citing the evidence_ids the "
        "tools returned.\n"
        "- For a quantitative finding, submit_claim with claim_type=quantitative and "
        "the method, series_ids, parameters, and claimed_value (copy the value from "
        "`calculate`). It will be independently recomputed; a wrong number is "
        "rejected.\n"
        "- Use web_search for current news, economic releases, and Fed/Treasury "
        "information, and cite the sources. Numeric values seen only in search are "
        "attribution-only unless a primary source is retrievable.\n"
        "- Prefer claims you can get VERIFIED: fetch prices and compute numbers. "
        "For 'what is happening in the market' or index moves, fetch SPY (S&P 500) "
        "and QQQ (Nasdaq-100) and compute period_return, max_drawdown, and "
        "realized_volatility. For 'which sectors are outperforming', fetch the SPDR "
        "sector ETFs (XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC) and "
        "SPY over the same window and compute relative_performance of each sector "
        "vs SPY, then submit quantitative claims for the leaders/laggards. For "
        "comparisons vs a past year, compute current-window statistics you can "
        "verify and clearly label any cross-year narrative as interpretation.\n"
        "- You cannot mark anything verified; only submit candidates. Your final "
        "prose is not shown to the user — the verified structured claims are.\n"
    )
    return market_research_instructions() + guide


def _register_web_citations(response: Any, collector: EvidenceCollector, now: datetime) -> None:
    """Preserve url citations from hosted web search as evidence records.

    Each preserved record is also aliased by every provider-native handle the
    citation carries (the URL and any id-like markers the model may echo as an
    ``evidence_id``), so a claim that cites ``turn…news…`` resolves to this
    record instead of being rejected as unknown evidence (spec §8).
    """
    raw = getattr(response, "output_text", "") or ""
    for citation in _iter_url_citations(response):
        url = citation.get("url")
        if not url:
            continue
        title = citation.get("title") or url
        snippet = citation.get("text") or citation.get("snippet")
        payload = json.dumps({"url": url, "title": title, "snippet": snippet}).encode("utf-8")
        evidence = collector.register(
            source_type=SourceKind.WEB_SEARCH_RESULT,
            provider="Web search",
            source_title=str(title)[:300],
            raw=payload,
            retrieved_at=now,
            source_url=str(url),
            excerpt=(str(snippet)[:2000] if snippet else _window(raw, citation)),
        )
        collector.register_alias(str(url), evidence.evidence_id)
        for marker in citation.get("markers", ()):
            collector.register_alias(marker, evidence.evidence_id)


#: Attributes on a citation annotation that may carry a provider-native handle
#: the model could echo as an evidence id (never ``type``, which is shared).
_MARKER_ATTRS = ("id", "ref_id", "reference", "source_id", "file_id", "citation_id")


def _iter_url_citations(response: Any) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    for item in getattr(response, "output", None) or []:
        if getattr(item, "type", None) != "message":
            continue
        for part in getattr(item, "content", None) or []:
            for ann in getattr(part, "annotations", None) or []:
                if getattr(ann, "type", None) in ("url_citation", "url"):
                    citations.append(
                        {
                            "url": getattr(ann, "url", None),
                            "title": getattr(ann, "title", None),
                            "text": getattr(ann, "text", None) or getattr(ann, "snippet", None),
                            "start": getattr(ann, "start_index", None),
                            "end": getattr(ann, "end_index", None),
                            "markers": _annotation_markers(ann),
                        }
                    )
    return citations


def _annotation_markers(ann: Any) -> tuple[str, ...]:
    """Collect provider-native handle strings from a citation annotation."""
    markers: list[str] = []
    for attr in _MARKER_ATTRS:
        value = getattr(ann, attr, None)
        if isinstance(value, str) and value.strip():
            markers.append(value.strip())
    return tuple(dict.fromkeys(markers))


def _window(text: str, citation: dict[str, Any]) -> str | None:
    start, end = citation.get("start"), citation.get("end")
    if isinstance(start, int) and isinstance(end, int) and 0 <= start < end <= len(text):
        return text[start:end][:2000]
    return None


def _note_unavailable(limitations: list[str], result: dict[str, Any]) -> None:
    source = result.get("source", "a data source")
    reason = result.get("reason", "unavailable")
    limitations.append(f"{source} was unavailable ({reason}); see tool notes.")


def _collect_limitations(
    limitations: list[str],
    verified: tuple[AgentClaim, ...],
    unresolved: tuple[AgentClaim, ...],
    exhausted_reason: str | None,
    config: AgentConfig,
) -> None:
    if exhausted_reason:
        limitations.append(
            f"Research budget was reached ({exhausted_reason}); findings may be partial."
        )
    if not verified:
        limitations.append("No assertion met the independent verification bar.")
    if unresolved:
        limitations.append(
            f"{len(unresolved)} candidate finding(s) could not be independently "
            "verified and are listed separately with their verdicts."
        )
    if not config.web_search_enabled:
        limitations.append("Web search was disabled for this run.")
