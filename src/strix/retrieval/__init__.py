"""Deterministic, auditable lexical retrieval infrastructure (§6.C).

A domain-independent inverted-index + BM25 ranking layer with an index
reconciliation guarantee (the index provably represents its corpus). All scoring
is exact/deterministic Decimal under a pinned precision — no floating point, no
embeddings, no network — so any result can be recomputed and audited. This is the
offline analogue of an OpenSearch/Elasticsearch lexical index; a hosted engine can
sit behind the same contracts without changing anything upstream.
"""
