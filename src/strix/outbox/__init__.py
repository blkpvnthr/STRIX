"""Durable transactional outbox (§4/§6).

A content-addressed, idempotent, lease-based event outbox backed by SQLite (the
stdlib, zero-install durable local backend). The schema and operations are written
so a PostgreSQL adapter can implement the same contract for institutional
deployments. At-least-once delivery with idempotent consumers; FIFO ordering;
bounded retries with dead-lettering; expired-lease recovery for crash/restart
safety; per-tenant isolation; and reconciliation.
"""
