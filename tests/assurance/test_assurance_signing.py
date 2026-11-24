"""Adversarial tests for detached Ed25519 certificate signing (R2-E).

A valid signature establishes *integrity* (the signed bytes are unaltered) and
*signer authenticity* (a specific key produced it). It never establishes that
the certificate's content is factually correct — that is a separate property
(R1 §13). These tests exercise the honest roundtrip and then attack it:
tampered certificate, wrong domain, revoked key, rotated key, unknown key,
cross-certificate replay, and private-key leakage.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from strix.assurance.signing import (
    Keyring,
    KeyStatus,
    Signature,
    SigningError,
    VerifyingKeyRecord,
    generate_keypair,
    load_private_key_from_env,
    sign_certificate,
    verify_signature,
)
from strix.evidence_graph.certificates import (
    ClaimCertificate,
    build_claim_certificate,
)
from strix.evidence_graph.nodes import PredicateName, PredicateResult, PredicateStatus

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
DOMAIN = "strix.claim.v1"
OTHER_DOMAIN = "strix.authorization.v1"


# --------------------------------------------------------------------------
# Fixtures / helpers
# --------------------------------------------------------------------------


def _claim_cert(digest: str = "a" * 64) -> ClaimCertificate:
    return build_claim_certificate(
        claim_id="CL-aaaaaaaaaaaa",
        canonical_claim_digest=digest,
        evidence_graph_snapshot_digest="b" * 64,
        supporting_evidence_ids=("EV-cccccccccccc",),
        dependency_closure=("EV-cccccccccccc",),
        predicate_results=(
            PredicateResult(predicate=PredicateName.SUPPORT, status=PredicateStatus.PASS),
        ),
        verification_policy_version="vpol-1",
        verifier_version="verifier-1",
        computation_certificate_refs=(),
        issued_at=NOW,
    )


def _status_of(keyring: Keyring, key_id: str) -> KeyStatus:
    record = keyring.get(key_id)
    assert record is not None
    return record.status


def _signed(
    cert: ClaimCertificate,
) -> tuple[bytes, VerifyingKeyRecord, Signature, Keyring]:
    private_bytes, record = generate_keypair(created_at=NOW)
    keyring = Keyring()
    keyring.register(record)
    signature = sign_certificate(
        cert, private_bytes, record, domain=DOMAIN, signed_at=NOW
    )
    return private_bytes, record, signature, keyring


# --------------------------------------------------------------------------
# Key generation + record shape
# --------------------------------------------------------------------------


def test_generate_keypair_yields_active_record_with_derived_key_id() -> None:
    private_bytes, record = generate_keypair(created_at=NOW)
    assert isinstance(private_bytes, bytes)
    assert len(private_bytes) == 32  # Ed25519 raw private key
    assert record.key_id.startswith("KEY-")
    assert len(record.key_id) == len("KEY-") + 16
    assert record.status is KeyStatus.ACTIVE
    # key_id is derived deterministically from the public key bytes.
    from strix.canonical import sha256_hex

    expected = "KEY-" + sha256_hex(bytes.fromhex(record.public_key_hex))[:16]
    assert record.key_id == expected


def test_generated_keys_are_distinct() -> None:
    _, record_a = generate_keypair(created_at=NOW)
    _, record_b = generate_keypair(created_at=NOW)
    assert record_a.key_id != record_b.key_id


# --------------------------------------------------------------------------
# Happy path
# --------------------------------------------------------------------------


def test_sign_then_verify_roundtrip() -> None:
    cert = _claim_cert()
    _, _, signature, keyring = _signed(cert)
    assert verify_signature(cert, signature, keyring, expected_domain=DOMAIN) is True


def test_signature_fields_are_well_formed() -> None:
    cert = _claim_cert()
    _, record, signature, _ = _signed(cert)
    assert signature.key_id == record.key_id
    assert signature.algorithm == "ed25519"
    assert signature.domain == DOMAIN
    from strix.canonical import canonical_bytes, sha256_hex

    assert signature.payload_digest == sha256_hex(canonical_bytes(cert))
    # signature_hex is raw Ed25519 signature = 64 bytes = 128 hex chars.
    assert len(bytes.fromhex(signature.signature_hex)) == 64


# --------------------------------------------------------------------------
# Adversarial: integrity
# --------------------------------------------------------------------------


def test_tampered_certificate_fails_verification() -> None:
    cert = _claim_cert()
    _, _, signature, keyring = _signed(cert)
    tampered = cert.model_copy(update={"verifier_version": "verifier-EVIL"})
    assert verify_signature(tampered, signature, keyring, expected_domain=DOMAIN) is False


def test_signature_for_one_certificate_does_not_verify_another() -> None:
    cert_a = _claim_cert(digest="a" * 64)
    cert_b = _claim_cert(digest="f" * 64)
    _, _, signature_a, keyring = _signed(cert_a)
    assert verify_signature(cert_a, signature_a, keyring, expected_domain=DOMAIN) is True
    assert verify_signature(cert_b, signature_a, keyring, expected_domain=DOMAIN) is False


def test_tampered_signature_hex_fails_verification() -> None:
    cert = _claim_cert()
    _, _, signature, keyring = _signed(cert)
    # Flip the last byte of the raw signature.
    raw = bytearray(bytes.fromhex(signature.signature_hex))
    raw[-1] ^= 0xFF
    forged = signature.model_copy(update={"signature_hex": raw.hex()})
    assert verify_signature(cert, forged, keyring, expected_domain=DOMAIN) is False


# --------------------------------------------------------------------------
# Adversarial: domain separation
# --------------------------------------------------------------------------


def test_wrong_expected_domain_fails_verification() -> None:
    cert = _claim_cert()
    _, _, signature, keyring = _signed(cert)
    assert verify_signature(cert, signature, keyring, expected_domain=OTHER_DOMAIN) is False


def test_signature_cannot_be_replayed_across_domains() -> None:
    """A signature produced for DOMAIN must not verify under another domain even
    if the attacker rewrites the Signature.domain field to match."""
    cert = _claim_cert()
    private_bytes, record, _, keyring = _signed(cert)
    sig_other = sign_certificate(
        cert, private_bytes, record, domain=OTHER_DOMAIN, signed_at=NOW
    )
    # Correct expected domain for the real domain still works.
    assert verify_signature(cert, sig_other, keyring, expected_domain=OTHER_DOMAIN) is True
    # Rewriting the domain label alone does not forge a DOMAIN signature: the
    # signed bytes were domain-separated, so Ed25519 verification fails.
    forged = sig_other.model_copy(update={"domain": DOMAIN})
    assert verify_signature(cert, forged, keyring, expected_domain=DOMAIN) is False


# --------------------------------------------------------------------------
# Adversarial: key lifecycle (assurance control cannot be overridden)
# --------------------------------------------------------------------------


def test_unknown_key_fails_verification() -> None:
    cert = _claim_cert()
    _, _, signature, _ = _signed(cert)
    empty_keyring = Keyring()  # key never registered
    assert verify_signature(cert, signature, empty_keyring, expected_domain=DOMAIN) is False


def test_revoked_key_fails_verification() -> None:
    cert = _claim_cert()
    _, record, signature, keyring = _signed(cert)
    keyring.revoke(record.key_id)
    assert _status_of(keyring, record.key_id) is KeyStatus.REVOKED
    assert verify_signature(cert, signature, keyring, expected_domain=DOMAIN) is False
    # Even the historical-verification escape hatch must not resurrect a revoked key.
    assert (
        verify_signature(
            cert, signature, keyring, expected_domain=DOMAIN, allow_rotated=True
        )
        is False
    )


def test_rotated_key_fails_verification_by_default() -> None:
    cert = _claim_cert()
    _, record, signature, keyring = _signed(cert)
    _, new_record = generate_keypair(created_at=NOW)
    keyring.rotate(record.key_id, new_record)
    assert _status_of(keyring, record.key_id) is KeyStatus.ROTATED
    assert verify_signature(cert, signature, keyring, expected_domain=DOMAIN) is False


def test_rotated_key_verifies_only_with_allow_rotated() -> None:
    cert = _claim_cert()
    _, record, signature, keyring = _signed(cert)
    _, new_record = generate_keypair(created_at=NOW)
    keyring.rotate(record.key_id, new_record)
    assert (
        verify_signature(
            cert, signature, keyring, expected_domain=DOMAIN, allow_rotated=True
        )
        is True
    )


# --------------------------------------------------------------------------
# Keyring semantics
# --------------------------------------------------------------------------


def test_keyring_duplicate_register_rejected() -> None:
    _, record = generate_keypair(created_at=NOW)
    keyring = Keyring()
    keyring.register(record)
    with pytest.raises(SigningError):
        keyring.register(record)


def test_keyring_rotate_unknown_key_rejected() -> None:
    _, new_record = generate_keypair(created_at=NOW)
    keyring = Keyring()
    with pytest.raises(SigningError):
        keyring.rotate("KEY-doesnotexist0", new_record)


def test_keyring_revoke_unknown_key_rejected() -> None:
    keyring = Keyring()
    with pytest.raises(SigningError):
        keyring.revoke("KEY-doesnotexist0")


def test_keyring_get_missing_returns_none() -> None:
    assert Keyring().get("KEY-missing00000") is None


def test_rotate_registers_new_active_key() -> None:
    _, record, _, keyring = _signed(_claim_cert())
    _, new_record = generate_keypair(created_at=NOW)
    keyring.rotate(record.key_id, new_record)
    assert _status_of(keyring, new_record.key_id) is KeyStatus.ACTIVE


# --------------------------------------------------------------------------
# Signing guards + secret handling
# --------------------------------------------------------------------------


def test_sign_with_mismatched_key_record_rejected() -> None:
    """The private key must correspond to the public key in the record."""
    cert = _claim_cert()
    private_bytes, _ = generate_keypair(created_at=NOW)
    _, other_record = generate_keypair(created_at=NOW)
    with pytest.raises(SigningError):
        sign_certificate(
            cert, private_bytes, other_record, domain=DOMAIN, signed_at=NOW
        )


def test_private_key_never_appears_in_signature_model() -> None:
    cert = _claim_cert()
    private_bytes, _, signature, _ = _signed(cert)
    blob = signature.model_dump_json()
    assert private_bytes.hex() not in blob
    for value in signature.model_dump().values():
        assert private_bytes.hex() != value
    assert private_bytes.hex() not in repr(signature)


def test_signed_at_excluded_from_signed_bytes() -> None:
    """signed_at is recorded for audit but must not change what is signed, so a
    signature made at a different wall-clock still verifies the same bytes."""
    cert = _claim_cert()
    private_bytes, record = generate_keypair(created_at=NOW)
    keyring = Keyring()
    keyring.register(record)
    later = datetime(2027, 6, 30, 9, 30, tzinfo=UTC)
    sig_a = sign_certificate(cert, private_bytes, record, domain=DOMAIN, signed_at=NOW)
    sig_b = sign_certificate(cert, private_bytes, record, domain=DOMAIN, signed_at=later)
    assert sig_a.signed_at != sig_b.signed_at
    # Both are valid signatures over identical domain-separated bytes.
    assert verify_signature(cert, sig_a, keyring, expected_domain=DOMAIN) is True
    assert verify_signature(cert, sig_b, keyring, expected_domain=DOMAIN) is True
    # Ed25519 is deterministic: identical signed bytes -> identical signature.
    assert sig_a.signature_hex == sig_b.signature_hex


def test_load_private_key_from_env_missing_raises() -> None:
    with pytest.raises(SigningError):
        load_private_key_from_env("STRIX_TEST_ABSENT_SIGNING_KEY")


def test_load_private_key_from_env_reads_hex(monkeypatch: pytest.MonkeyPatch) -> None:
    private_bytes, _ = generate_keypair(created_at=NOW)
    monkeypatch.setenv("STRIX_TEST_SIGNING_KEY", private_bytes.hex())
    loaded = load_private_key_from_env("STRIX_TEST_SIGNING_KEY")
    assert loaded == private_bytes


def test_load_private_key_from_env_rejects_bad_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STRIX_TEST_SIGNING_KEY", "ab" * 10)  # not 32 bytes
    with pytest.raises(SigningError):
        load_private_key_from_env("STRIX_TEST_SIGNING_KEY")
