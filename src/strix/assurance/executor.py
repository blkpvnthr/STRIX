"""Simulation-only action executor (R1 §18, §20).

The :class:`SandboxExecutor` dispatches an authorized action **in simulation
only**: it performs no live external execution and places no brokerage orders.
It refuses to dispatch without a valid, matching
:class:`~strix.evidence_graph.certificates.AuthorizationCertificate`, and it
honors idempotency — re-dispatching the same ``idempotency_key`` returns the
original :class:`ExecutorResult` with no double effect (the atomic
duplicate-action guard generalized from the C-engine).
"""

from __future__ import annotations

from strix.assurance.authorization import ActionRequest, AuthorizationError, Decision
from strix.canonical import canonical_hash
from strix.evidence_graph.certificates import (
    AuthorizationCertificate,
    validate_authorization_certificate,
)
from strix.models import StrixModel

__all__ = ["ExecutorResult", "SandboxExecutor"]


class ExecutorResult(StrixModel):
    """The simulated outcome of dispatching one authorized action.

    ``acknowledged`` records only that the executor accepted and simulated the
    action — it is **not** evidence that the intended effect occurred. Only
    independent outcome reconciliation (R1 §20) may establish success.
    """

    action_id: str
    authorization_certificate_id: str
    acknowledged: bool
    simulated_state: dict[str, str]
    executor: str


class SandboxExecutor:
    """A deterministic, simulation-only executor with an idempotency guard.

    Never performs live external execution. Keeps a per-key ledger so a repeated
    ``idempotency_key`` yields the identical prior result without re-simulating.
    """

    def __init__(self, *, name: str = "sandbox") -> None:
        self._name = name
        self._ledger: dict[str, ExecutorResult] = {}

    @property
    def name(self) -> str:
        """The executor identity this sandbox dispatches as."""
        return self._name

    def _reject_if_invalid(
        self, certificate: AuthorizationCertificate, request: ActionRequest
    ) -> None:
        """Refuse to dispatch unless the certificate is valid and binds *request*."""
        if not validate_authorization_certificate(certificate):
            raise AuthorizationError(
                "refusing to dispatch: authorization certificate failed validation"
            )
        if certificate.decision != Decision.GRANTED.value:
            raise AuthorizationError(
                "refusing to dispatch: authorization certificate is not a grant"
            )
        if certificate.authorized_executor != self._name:
            raise AuthorizationError(
                "refusing to dispatch: certificate authorizes a different executor"
            )
        if certificate.action_request_digest != canonical_hash(_identity_payload(request)):
            raise AuthorizationError(
                "refusing to dispatch: certificate does not bind this exact request"
            )
        if certificate.idempotency_key != request.idempotency_key:
            raise AuthorizationError(
                "refusing to dispatch: idempotency key does not match the certificate"
            )

    def dispatch(
        self, certificate: AuthorizationCertificate, request: ActionRequest
    ) -> ExecutorResult:
        """Simulate the authorized action, honoring idempotency.

        A repeated ``idempotency_key`` returns the first result verbatim (no
        double effect). Raises :class:`AuthorizationError` without a valid,
        request-binding grant certificate.
        """
        key = request.idempotency_key
        existing = self._ledger.get(key)
        if existing is not None:
            return existing
        self._reject_if_invalid(certificate, request)
        result = ExecutorResult(
            action_id=request.action_id,
            authorization_certificate_id=certificate.certificate_id,
            acknowledged=True,
            simulated_state=dict(request.parameters),
            executor=self._name,
        )
        self._ledger[key] = result
        return result


def _identity_payload(request: ActionRequest) -> dict[str, object]:
    """The request's content payload with its self-referential id removed."""
    payload = request.model_dump()
    payload.pop("action_id", None)
    return payload
