"""RS256 JWT authentication between the node runtime and the Coda cloud.

Every request from the node to the Coda API (webhooks, heartbeats,
reconnect) is authenticated with a short-lived JWT signed with an RSA
private key.  The cloud verifies the signature using the corresponding
public key registered during self-service bootstrap.

Key concepts:

* **KeyPair** -- an RSA keypair generated locally or received from the
  self-service endpoint.
* **sign_token** -- creates a signed JWT for outbound requests.
* **verify_token** / **verify_token_with_key** -- validate inbound JWTs
  (used primarily in tests and potential future inbound auth).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

__all__ = [
    "DEFAULT_ISSUER",
    "DEFAULT_TTL",
    "KeyPair",
    "generate_keypair",
    "sign_token",
    "verify_token",
    "verify_token_with_key",
]

DEFAULT_ISSUER = "coda"
DEFAULT_TTL = timedelta(hours=1)
KEY_SIZE = 2048


@dataclass(frozen=True, slots=True)
class KeyPair:
    """RSA keypair for JWT authentication."""

    private_key_pem: str
    public_key_pem: str
    key_id: str


def generate_keypair(key_id: str) -> KeyPair:
    """Generate a fresh PEM-encoded RSA-2048 keypair.

    Args:
        key_id: Logical identifier embedded in JWTs as the ``kid`` header.
            Typically the QPU node identifier.

    Returns:
        A :class:`KeyPair` containing PEM-encoded private and public keys.
    """
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=KEY_SIZE)

    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )

    return KeyPair(
        private_key_pem=private_pem,
        public_key_pem=public_pem,
        key_id=key_id,
    )


def sign_token(
    subject: str,
    private_key_pem: str,
    *,
    issuer: str = DEFAULT_ISSUER,
    ttl: timedelta = DEFAULT_TTL,
    key_id: str | None = None,
) -> str:
    """Create a short-lived RS256-signed JWT.

    The token carries ``sub``, ``iss``, ``iat``, and ``exp`` claims and a
    ``kid`` header so the verifier can look up the correct public key.

    Args:
        subject: The ``sub`` claim -- usually the QPU node identifier.
        private_key_pem: PEM-encoded RSA private key used to sign.
        issuer: The ``iss`` claim.
        ttl: Token lifetime from now.
        key_id: Explicit ``kid`` header value.  Defaults to *subject*.

    Returns:
        A compact-serialised JWT string.
    """
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iss": issuer,
        "iat": now,
        "exp": now + ttl,
    }
    headers = {"kid": key_id or subject}
    return jwt.encode(payload, private_key_pem, algorithm="RS256", headers=headers)


def verify_token(
    token: str,
    get_public_key: Callable[[str], str | None],
    *,
    issuer: str = DEFAULT_ISSUER,
) -> dict[str, object]:
    """Verify and decode a JWT by resolving its ``kid`` to a public key.

    Args:
        token: The compact-serialised JWT to verify.
        get_public_key: Callable that maps a ``kid`` string to a
            PEM-encoded public key, or ``None`` if the key is unknown.
        issuer: Expected ``iss`` claim value.

    Returns:
        The decoded payload as a dictionary.

    Raises:
        jwt.InvalidTokenError: If the token is malformed, the ``kid`` is
            missing or unknown, or signature / claim validation fails.
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise jwt.InvalidTokenError(f"Malformed token header: {exc}") from exc

    kid = header.get("kid")
    if not kid:
        raise jwt.InvalidTokenError("Token missing 'kid' header")

    public_key_pem = get_public_key(kid)
    if not public_key_pem:
        raise jwt.InvalidTokenError(f"Unknown key_id: {kid}")

    result: dict[str, object] = jwt.decode(
        token,
        public_key_pem,
        algorithms=["RS256"],
        issuer=issuer,
        options={"require": ["sub", "iss", "exp", "iat"]},
    )
    return result


def verify_token_with_key(
    token: str,
    public_key_pem: str,
    *,
    issuer: str = DEFAULT_ISSUER,
) -> dict[str, object]:
    """Verify and decode a JWT when the public key is already known.

    Unlike :func:`verify_token`, this skips the ``kid`` lookup and uses
    the provided key directly.

    Args:
        token: The compact-serialised JWT to verify.
        public_key_pem: PEM-encoded RSA public key.
        issuer: Expected ``iss`` claim value.

    Returns:
        The decoded payload as a dictionary.

    Raises:
        jwt.InvalidTokenError: If signature or claim validation fails.
    """
    result: dict[str, object] = jwt.decode(
        token,
        public_key_pem,
        algorithms=["RS256"],
        issuer=issuer,
        options={"require": ["sub", "iss", "exp", "iat"]},
    )
    return result
