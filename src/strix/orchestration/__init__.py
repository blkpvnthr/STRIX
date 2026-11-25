"""Scheduler-independent DAG orchestration (Wave 11 / §7).

A small, deterministic, in-process DAG runner so STRIX data-engineering (and any
other) pipelines execute WITHOUT requiring a running Airflow instance: topological
ordering, dependency-aware skipping on upstream failure, bounded retries, and
checkpoint/resume. An Airflow adapter can map the same :class:`Dag` onto operators,
but correctness is established here, offline.
"""
