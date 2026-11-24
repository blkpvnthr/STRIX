"""Domain-independent independent-execution authorization subsystem (GAP-001).

Generalizes the C-engine deterministic risk-engine mechanism — an ordered,
short-circuit-free constraint gauntlet with typed deterministic reject reason
codes and an atomic duplicate-action guard — into a trading-agnostic
authorization kernel (R1 §18, §20). External state-changing execution is
disabled by default; the sandbox executor is simulation-only; and an executor
acknowledgement never establishes success on its own (R1 §20).
"""
