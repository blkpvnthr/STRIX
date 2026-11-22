"""Historical and incremental ingestion into the immutable Bronze layer (DE-2).

Provider extractors acquire raw bytes from authoritative endpoints; the
:class:`~strix.lakehouse.ingest.runner.IngestionRunner` preserves each payload via
the DE-1 :class:`~strix.lakehouse.bronze.BronzeIngestor` (immutable, deduplicated,
provenance-tracked), advances persistent checkpoints/watermarks, applies rate
limiting and bounded exponential-backoff retries, recovers from partial failures,
detects missing windows, and reconciles source batches against Bronze.

Raw-artifact deduplication (identical bytes stored once) is **not** the same as
observation-level deduplication, which is validated during Silver normalization
(DE-3). This layer guarantees only that every raw payload is preserved exactly
once and fully traceable.
"""
