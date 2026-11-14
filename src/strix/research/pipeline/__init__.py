"""The prepare() / propose() / finalize() orchestration boundary.

Phase 9 of the neuro-symbolic platform:

    prepare()   immutable snapshot + request -> parsing -> retrieval
                -> PreparedResearch                              (deterministic)
    propose()   PreparedResearch evidence packet -> injected
                ProposalProvider -> recorded ProposalSet          (NOT deterministic)
    finalize()  PreparedResearch + ProposalSet -> structural
                validation -> PendingResearchResult               (deterministic)

``propose()`` is the only seam that may call a non-deterministic
provider; its output is always a *recorded* proposal set. Repeating
``prepare()`` or ``finalize()`` with identical inputs always produces the
same ID — proposal generation itself is not assumed reproducible.

No result this phase produces may ever be marked verified: a
``PendingResearchResult`` structurally checks that citations resolve and
that no proposal smuggled in a non-PROPOSED status, nothing more. Full
semantic verification, trusted findings, reporting, persistence, and
replay are Phase 11.
"""
