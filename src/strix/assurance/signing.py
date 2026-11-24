"""Detached Ed25519 signatures over STRIX certificates (R2-E).

R1 §13 certificates are *content-addressed*: a ``certificate_id`` derived from
canonical content already detects tampering with any deterministic field. This
module adds a second, orthogonal property on top of that — **authenticity**: a
detached :class:`Signature` proves that a holder of a specific private key
attested to the exact bytes of a certificate, and that those bytes have not
changed since.

Detached, not embedded
----------------------
Signatures live *beside* certificates, never inside them. The certificate stays
byte-for-byte identical whether or not it has been signed, so its content id and
hash are unaffected, and the same certificate may be signed independently by
several keys and in several domains.

Domain separation
-----------------
The bytes actually fed to Ed25519 are **not** the certificate bytes. They are
the canonical serialization of ``{"domain", "schema_version", "payload_digest"}``
where ``payload_digest`` is the SHA-256 of the certificate's canonical bytes.
Because the domain string is inside the signed message, a signature minted for
one domain (e.g. a claim certificate) cannot be replayed as a valid signature in
another (e.g. an authorization) — rewriting the ``Signature.domain`` label alone
does not forge a signature, because the signed bytes no longer match.

Key lifecycle is fail-closed
----------------------------
Verification consults a :class:`Keyring`. Only an **active** key verifies. A
``rotated`` key verifies only when the caller explicitly opts into historical
verification via ``allow_rotated=True``; a ``revoked`` key and an unknown key
**never** verify, regardless of any flag. These are assurance controls and
cannot be overridden by the data being checked.

What a valid signature is — and is NOT
--------------------------------------
A valid signature establishes **integrity** (the certificate bytes are
unaltered) and **signer authenticity** (a specific key produced it). It does
**not** establish that the certificate's content is factually correct, nor that
the action it attests is safe or profitable — that is cryptographic assurance,
not epistemic truth (R1 §13).

Secret handling
---------------
Private key material is handled as raw bytes and is **never** logged, embedded
in a :class:`Signature`, or otherwise persisted by this module. In production,
private keys MUST come from a dedicated secret store (e.g. a KMS/HSM or a
secrets manager); :func:`load_private_key_from_env` is a development convenience
that reads a hex-encoded raw key from an environment variable and never echoes
its value, not a recommendation to keep long-lived keys in the environment.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from enum import StrEnum

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import AwareDatetime

from strix.canonical import canonical_bytes, sha256_hex
from strix.errors import StrixError
from strix.models import StrixModel

__all__ = [
    "ALGORITHM",
    "SIGNATURE_SCHEMA_VERSION",
    "KeyStatus",
    "Keyring",
    "Signature",
    "SigningError",
    "VerifyingKeyRecord",
    "generate_keypair",
    "load_private_key_from_env",
    "sign_certificate",
    "verify_signature",
]

#: The only signature algorithm this module emits or accepts.
ALGORITHM = "ed25519"

#: Schema version of the domain-separated signing envelope. It is part of the
#: signed bytes, so bumping it invalidates every prior signature by design.
SIGNATURE_SCHEMA_VERSION = "strix-sig-1"

#: Raw Ed25519 private key size (bytes).
_PRIVATE_KEY_LEN = 32

#: Length of the public-key hash prefix used in ``key_id`` (hex chars).
_KEY_ID_HASH_LEN = 16


class SigningError(StrixError):
    """A signing operation could not be trusted or completed.

    Covers a private key that does not match its declared public record, a
    missing/malformed key from the environment, and keyring misuse (registering
    a duplicate key, or rotating/revoking an unknown one). Verification itself
    never raises — it is fail-closed and returns ``False`` on any problem.
    """


class KeyStatus(StrEnum):
    """Lifecycle state of a verifying key.

    Only :attr:`ACTIVE` verifies unconditionally. :attr:`ROTATED` verifies only
    under an explicit historical-verification opt-in; :attr:`REVOKED` never
    verifies.
    """

    ACTIVE = "active"
    ROTATED = "rotated"
    REVOKED = "revoked"


class VerifyingKeyRecord(StrixModel):
    """The public half of a signing key plus its lifecycle status.

    ``key_id`` is derived from the public key bytes
    (``"KEY-" + sha256(public_bytes)[:16]``) so it is stable and content-bound.
    Holds **no** private material.
    """

    key_id: str
    public_key_hex: str
    status: KeyStatus
    created_at: AwareDatetime


class Signature(StrixModel):
    """A detached Ed25519 signature over one certificate.

    The signed bytes are the canonical serialization of
    ``{"domain", "schema_version", "payload_digest"}`` — ``signed_at`` is
    recorded purely for audit and is **excluded from the signed message and from
    any content id** (two signatures of the same bytes at different wall-clocks
    sign identical data). Carries no private key material.
    """

    key_id: str
    algorithm: str = ALGORITHM
    domain: str
    schema_version: str
    #: SHA-256 hex of the signed certificate's canonical bytes.
    payload_digest: str
    signature_hex: str
    #: Audit-only issuance wall-clock; never enters the signed bytes or any id.
    signed_at: AwareDatetime


# --------------------------------------------------------------------------
# Internal helpers
# --------------------------------------------------------------------------


def _public_bytes(public_key: Ed25519PublicKey) -> bytes:
    """Return the raw 32-byte public key encoding."""
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _private_bytes(private_key: Ed25519PrivateKey) -> bytes:
    """Return the raw 32-byte private key encoding (never logged or persisted)."""
    return private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _derive_key_id(public_bytes: bytes) -> str:
    """Derive the stable, content-bound ``key_id`` from raw public key bytes."""
    return "KEY-" + sha256_hex(public_bytes)[:_KEY_ID_HASH_LEN]


def _payload_digest(certificate: StrixModel) -> str:
    """SHA-256 hex of *certificate*'s canonical bytes (the signed payload)."""
    return sha256_hex(canonical_bytes(certificate))


def _signed_message(domain: str, payload_digest: str) -> bytes:
    """Build the domain-separated bytes actually fed to Ed25519.

    The domain is inside the message, so a signature is bound to its domain and
    cannot be replayed into another by relabelling the :class:`Signature`.
    """
    return canonical_bytes(
        {
            "domain": domain,
            "schema_version": SIGNATURE_SCHEMA_VERSION,
            "payload_digest": payload_digest,
        }
    )


# --------------------------------------------------------------------------
# Key generation
# --------------------------------------------------------------------------


def generate_keypair(
    *, created_at: AwareDatetime | None = None
) -> tuple[bytes, VerifyingKeyRecord]:
    """Generate a fresh Ed25519 keypair.

    Returns ``(private_key_bytes, verifying_key_record)``. The raw private key
    bytes are returned to the caller and never stored by this module — the
    caller is responsible for placing them in a secret store. ``created_at``
    defaults to the current UTC time and is recorded on the public record only.
    """
    private_key = Ed25519PrivateKey.generate()
    public_bytes = _public_bytes(private_key.public_key())
    record = VerifyingKeyRecord(
        key_id=_derive_key_id(public_bytes),
        public_key_hex=public_bytes.hex(),
        status=KeyStatus.ACTIVE,
        created_at=created_at if created_at is not None else datetime.now(UTC),
    )
    return _private_bytes(private_key), record


# --------------------------------------------------------------------------
# Signing
# --------------------------------------------------------------------------


def sign_certificate(
    certificate: StrixModel,
    private_key_bytes: bytes,
    key_record: VerifyingKeyRecord,
    *,
    domain: str,
    signed_at: AwareDatetime,
) -> Signature:
    """Produce a detached, domain-separated Ed25519 signature over *certificate*.

    The signed bytes are :func:`_signed_message` over the certificate's payload
    digest, so the signature is bound to *domain*. The supplied
    ``private_key_bytes`` MUST correspond to ``key_record`` (same public key) or
    a :class:`SigningError` is raised — this prevents silently attributing a
    signature to a record it was not produced with. The private key is used
    transiently and never placed in the returned :class:`Signature`.
    """
    try:
        private_key = Ed25519PrivateKey.from_private_bytes(private_key_bytes)
    except (ValueError, TypeError) as exc:  # malformed raw key
        raise SigningError("invalid Ed25519 private key material") from exc

    derived_public = _public_bytes(private_key.public_key()).hex()
    if derived_public != key_record.public_key_hex:
        # Do NOT include key material in the message.
        raise SigningError(
            f"private key does not match verifying key record {key_record.key_id}"
        )

    payload_digest = _payload_digest(certificate)
    message = _signed_message(domain, payload_digest)
    signature_bytes = private_key.sign(message)
    return Signature(
        key_id=key_record.key_id,
        algorithm=ALGORITHM,
        domain=domain,
        schema_version=SIGNATURE_SCHEMA_VERSION,
        payload_digest=payload_digest,
        signature_hex=signature_bytes.hex(),
        signed_at=signed_at,
    )


# --------------------------------------------------------------------------
# Verification (fail-closed)
# --------------------------------------------------------------------------


def verify_signature(
    certificate: StrixModel,
    signature: Signature,
    keyring: Keyring,
    *,
    expected_domain: str,
    allow_rotated: bool = False,
) -> bool:
    """Return ``True`` iff *signature* is a valid attestation of *certificate*.

    Fail-closed: any mismatch, unknown/non-active key, tampered field, or
    malformed value yields ``False`` (never an exception). Checks, in order:

    1. algorithm and schema version are the ones this module emits;
    2. the signature's declared domain equals *expected_domain*;
    3. the payload digest recomputed from *certificate* equals the signed digest
       (this catches both a tampered certificate and a signature lifted from a
       different certificate);
    4. the key is present in *keyring* and ``ACTIVE`` — or ``ROTATED`` only when
       ``allow_rotated`` is set; a ``REVOKED`` or unknown key is always rejected;
    5. the raw Ed25519 verification over the rebuilt domain-separated bytes.

    A ``True`` result attests integrity and signer authenticity — **not** that
    the certificate's content is factually correct (R1 §13).
    """
    if signature.algorithm != ALGORITHM:
        return False
    if signature.schema_version != SIGNATURE_SCHEMA_VERSION:
        return False
    if signature.domain != expected_domain:
        return False

    # Fail closed: a certificate that cannot be canonically serialized must yield
    # False, never propagate an exception (the function's documented contract).
    try:
        expected_digest = _payload_digest(certificate)
    except (TypeError, ValueError):
        return False
    if signature.payload_digest != expected_digest:
        return False

    record = keyring.get(signature.key_id)
    if record is None:
        return False
    if record.status is KeyStatus.REVOKED:
        return False
    if record.status is KeyStatus.ROTATED and not allow_rotated:
        return False
    # Only ACTIVE (always) or ROTATED-with-allow_rotated reach here.

    message = _signed_message(expected_domain, expected_digest)
    try:
        public_key = Ed25519PublicKey.from_public_bytes(
            bytes.fromhex(record.public_key_hex)
        )
        public_key.verify(bytes.fromhex(signature.signature_hex), message)
    except (InvalidSignature, ValueError, TypeError):
        return False
    return True


# --------------------------------------------------------------------------
# Keyring
# --------------------------------------------------------------------------


class Keyring:
    """A mutable registry of verifying key records keyed by ``key_id``.

    Holds only public key records (never private material). Lifecycle
    transitions are explicit and one-way in practice: ``register`` a new key,
    ``rotate`` an old key to :attr:`KeyStatus.ROTATED` while registering its
    replacement, and ``revoke`` a compromised key to :attr:`KeyStatus.REVOKED`.
    :func:`verify_signature` trusts only the current status recorded here.
    """

    def __init__(self) -> None:
        self._keys: dict[str, VerifyingKeyRecord] = {}

    def register(self, key_record: VerifyingKeyRecord) -> None:
        """Register a new verifying key.

        Raises :class:`SigningError` if a record with the same ``key_id`` is
        already present — a key is never silently replaced.
        """
        if key_record.key_id in self._keys:
            raise SigningError(f"key already registered: {key_record.key_id}")
        self._keys[key_record.key_id] = key_record

    def rotate(self, old_key_id: str, new_key_record: VerifyingKeyRecord) -> None:
        """Mark *old_key_id* as rotated and register *new_key_record* as active.

        Raises :class:`SigningError` if the old key is unknown or the new key is
        already registered. After rotation the old key verifies only under
        ``allow_rotated`` historical verification.
        """
        old = self._keys.get(old_key_id)
        if old is None:
            raise SigningError(f"cannot rotate unknown key: {old_key_id}")
        self.register(new_key_record)
        self._keys[old_key_id] = old.model_copy(update={"status": KeyStatus.ROTATED})

    def revoke(self, key_id: str) -> None:
        """Mark *key_id* as revoked. A revoked key never verifies again.

        Raises :class:`SigningError` if the key is unknown.
        """
        existing = self._keys.get(key_id)
        if existing is None:
            raise SigningError(f"cannot revoke unknown key: {key_id}")
        self._keys[key_id] = existing.model_copy(update={"status": KeyStatus.REVOKED})

    def get(self, key_id: str) -> VerifyingKeyRecord | None:
        """Return the current record for *key_id*, or ``None`` if unknown."""
        return self._keys.get(key_id)


# --------------------------------------------------------------------------
# Secret handling
# --------------------------------------------------------------------------


def load_private_key_from_env(var: str) -> bytes:
    """Load a hex-encoded raw Ed25519 private key from environment variable *var*.

    Development convenience only. Returns the 32 raw key bytes. Raises
    :class:`SigningError` if the variable is unset/empty or does not decode to a
    valid 32-byte key. The key value is **never** logged or placed in the raised
    message. In production, read keys from a dedicated secret store (KMS/HSM or a
    secrets manager), not from the process environment.
    """
    raw = os.environ.get(var)
    if not raw:
        raise SigningError(f"private key environment variable is not set: {var}")
    try:
        key_bytes = bytes.fromhex(raw.strip())
    except ValueError as exc:
        # Deliberately do not echo the variable's value.
        raise SigningError(
            f"private key in {var} is not valid hex"
        ) from exc
    if len(key_bytes) != _PRIVATE_KEY_LEN:
        raise SigningError(
            f"private key in {var} must be {_PRIVATE_KEY_LEN} bytes, "
            f"got {len(key_bytes)}"
        )
    return key_bytes
