"""DE-5 dbt transformation layer: controlled dbt orchestration over the STRIX
analytical warehouse, versioned calculation contracts, and independent
cross-validation of SQL marts against the Decimal Python calculators.

The transformation layer is NOT the verifier. A published mart value never
receives a verification verdict automatically; :mod:`strix.lakehouse.transform.
verification` recomputes supported claims from the preserved Silver/Bronze
evidence using the same :mod:`strix.agent.calculations` the research verifier uses.
"""

from __future__ import annotations

TRANSFORM_VERSION = "0.1.0"
