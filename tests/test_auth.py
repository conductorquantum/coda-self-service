"""Tests for RS256 JWT helpers."""

from datetime import timedelta

import jwt
import pytest

from self_service.server.auth import (
    DEFAULT_ISSUER,
    KEY_SIZE,
    KeyPair,
    generate_keypair,
    sign_token,
    verify_token,
    verify_token_with_key,
)


@pytest.fixture
def keypair() -> KeyPair:
    return generate_keypair("test-node-001")


class TestGenerateKeypair:
    def test_returns_valid_pem_keys(self, keypair: KeyPair) -> None:
        assert keypair.private_key_pem.startswith("-----BEGIN PRIVATE KEY-----")
        assert keypair.public_key_pem.startswith("-----BEGIN PUBLIC KEY-----")
        assert keypair.key_id == "test-node-001"

    def test_unique_keys_per_call(self) -> None:
        first = generate_keypair("a")
        second = generate_keypair("b")
        assert first.private_key_pem != second.private_key_pem
        assert first.public_key_pem != second.public_key_pem

    def test_key_size(self, keypair: KeyPair) -> None:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

        private_key = load_pem_private_key(
            keypair.private_key_pem.encode(), password=None
        )
        assert isinstance(private_key, RSAPrivateKey)
        assert private_key.key_size == KEY_SIZE


class TestVerifyToken:
    def test_valid_token(self, keypair: KeyPair) -> None:
        token = sign_token("test-node-001", keypair.private_key_pem)

        def get_key(kid: str) -> str | None:
            return keypair.public_key_pem if kid == "test-node-001" else None

        payload = verify_token(token, get_key)
        assert payload["sub"] == "test-node-001"
        assert payload["iss"] == DEFAULT_ISSUER

    def test_unknown_kid(self, keypair: KeyPair) -> None:
        token = sign_token("test-node-001", keypair.private_key_pem)
        with pytest.raises(jwt.InvalidTokenError, match="Unknown key_id"):
            verify_token(token, lambda _kid: None)

    def test_verify_token_with_key(self, keypair: KeyPair) -> None:
        token = sign_token(
            "test-node-001", keypair.private_key_pem, ttl=timedelta(minutes=5)
        )
        payload = verify_token_with_key(token, keypair.public_key_pem)
        assert payload["sub"] == "test-node-001"

    def test_rejects_wrong_issuer(self, keypair: KeyPair) -> None:
        token = sign_token("node", keypair.private_key_pem, issuer="other")
        with pytest.raises(jwt.InvalidIssuerError):
            verify_token_with_key(token, keypair.public_key_pem)
