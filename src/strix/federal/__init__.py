"""Federal procurement application adapter for STRIX.

This package is an *application adapter*: it maps federal spending data
(awards, modifications, agencies, contractors) onto STRIX's assurance
primitives without modifying the assurance core. Adapters here are
fixture-backed — no live network, no credentials.

Federal money kinds (obligation, deobligation, outlay, disbursement, award
amount, modification amount) are kept semantically distinct and are never
treated as interchangeable, and personal double-entry semantics are never
applied to procurement data.
"""
