"""STRIX engineering domain: evidence-preserving engineering data compiler.

Transforms heterogeneous legacy technical records (ReqIF, XML, CSV,
structured TXT) into an authoritative digital system model in which every
element and relationship resolves to exact preserved source evidence:

    source artifact -> anchored engineering fact -> typed evidence
    -> candidate model element/relationship -> deterministic verification
    -> verified engineering model -> replayable export

This is an offline prototype operating on synthetic public data only. PDF,
Office formats, databases, archives, scientific containers, LLM-assisted
extraction, and OCR are future research, not implemented capabilities.
"""

#: Version of the engineering compilation contract. Recorded in every
#: engineering run manifest so replays can detect contract drift.
ENGINEERING_PIPELINE_VERSION = "0.1.0"
