"""Institutional instance isolation (§13).

Multiple institutions can run on one STRIX deployment without ever sharing audit
chains, signing keys, policies, or resource identifiers. Each institution gets a
content-addressed identity and an :class:`~strix.institutional.isolation.InstanceContext`
that scopes a dedicated audit-ledger root and keyring and namespaces every resource
id, enforcing the cross-institution trust boundary fail-closed. The isolation layer
composes the existing audit ledger and signing keyring rather than reimplementing
them.
"""
