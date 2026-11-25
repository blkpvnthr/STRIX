"""Security operating modes and default-deny policy (§10).

STRIX runs in one of four operating modes that bound its network-facing and
assurance-bypass capabilities. Closed-institutional and disconnected modes are
default-deny: external research, cloud inference, and the ``--no-assurance`` escape
are all disabled, and an unrecognized mode fails closed to the most restrictive
(disconnected) mode. Enforcement is layered above the assurance gateway, not in
place of it.
"""
