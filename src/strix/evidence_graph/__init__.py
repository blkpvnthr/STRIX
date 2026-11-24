"""R1 evidence graph G=(V,E,tau,pi): typed nodes, edges, and verification policy.

This package implements the typed foundation of the R1 evidence graph
(R1 §9): raw observations, pre-verification candidate claims, typed
relationship edges, and the trusted, versioned verification policy that
decides predicate applicability. Every identity-bearing node carries a
content-derived id via :mod:`strix.canonical`, excluding its own id and any
process wall-clock from the hashed payload.
"""
