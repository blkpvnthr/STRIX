"""Loading, validation, and execution policy for the project manifest.

Schema capability and execution policy are deliberately separate:
- The SCHEMA (:class:`EngineeringProjectManifest`) can represent real data
  (``synthetic: false``) and arbitrary validated handling markings, so future
  adapters need no redesign.
- The v2 COMMAND enforces a synthetic-public-only POLICY via
  :func:`enforce_v2_policy`; refusal is a policy error, not a schema error.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import ValidationError

from strix.engineering.models import (
    V2_POLICY_MARKINGS,
    EngineeringProjectManifest,
)
from strix.errors import EngineeringSourceError

#: Fixed name of the project manifest inside an input directory.
MANIFEST_NAME = "engineering-project.json"

_SUPPORTED_MANIFEST_VERSIONS = frozenset({"1.0.0"})


def _forbid_float(text: str) -> None:
    raise EngineeringSourceError(
        f"project manifest contains a JSON float ({text!r}); floats are forbidden"
    )


def load_project_manifest(raw: bytes) -> EngineeringProjectManifest:
    """Strictly parse and validate project-manifest bytes."""
    try:
        payload: Any = json.loads(raw.decode("utf-8"), parse_float=_forbid_float)
    except UnicodeDecodeError as exc:
        raise EngineeringSourceError(f"project manifest is not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise EngineeringSourceError(f"project manifest is not valid JSON: {exc}") from exc
    try:
        manifest = EngineeringProjectManifest.model_validate(payload)
    except ValidationError as exc:
        raise EngineeringSourceError(f"project manifest failed schema validation: {exc}") from exc
    if manifest.manifest_version not in _SUPPORTED_MANIFEST_VERSIONS:
        raise EngineeringSourceError(
            f"unsupported manifest_version {manifest.manifest_version!r}; "
            f"supported: {sorted(_SUPPORTED_MANIFEST_VERSIONS)}"
        )
    declared = [source.file for source in manifest.sources]
    if len(set(declared)) != len(declared):
        raise EngineeringSourceError("project manifest declares a source file twice")
    if MANIFEST_NAME in declared:
        raise EngineeringSourceError(f"{MANIFEST_NAME} must not declare itself as a source")
    if manifest.ground_truth is not None and manifest.ground_truth in declared:
        raise EngineeringSourceError(
            "ground_truth must not also be declared as an engineering source"
        )
    return manifest


def enforce_v2_policy(manifest: EngineeringProjectManifest) -> None:
    """The v2 synthetic-public-only execution policy (not a schema rule)."""
    if not manifest.synthetic:
        raise EngineeringSourceError(
            "v2 policy refusal: this command only compiles synthetic "
            "demonstration data (manifest declares synthetic=false); the "
            "manifest schema itself may represent real data for future use"
        )
    for source in manifest.sources:
        disallowed = [m for m in source.handling if m not in V2_POLICY_MARKINGS]
        if disallowed:
            raise EngineeringSourceError(
                f"v2 policy refusal: source {source.file!r} carries handling "
                f"markings {disallowed} outside the permitted "
                f"{sorted(V2_POLICY_MARKINGS)}"
            )
