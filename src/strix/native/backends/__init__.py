"""Computational backends for the native quantitative layer (R1 §5.3).

The :class:`~strix.native.backends.python_reference.PythonReferenceBackend` is the
independent-validation baseline. Native-CPU (pybind11/C++) and Metal backends are
certified for numerical parity against it before use.
"""

from __future__ import annotations
