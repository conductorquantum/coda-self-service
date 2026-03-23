# JWT Signing & Verification

## Token Structure

JWTs use the RS256 algorithm (RSA with SHA-256) and carry:

### Header

```json
{
  "alg": "RS256",
  "kid": "qpu-my-qpu-1710000000000"
}
```

The `kid` (key ID) lets the cloud look up the correct public key when
multiple QPUs are registered.

### Payload

```json
{
  "sub": "my-qpu",
  "iss": "coda",
  "iat": 1710000000,
  "exp": 1710003600
}
```

| Claim | Value | Description |
|---|---|---|
| `sub` | QPU ID | Identifies the sending node. |
| `iss` | `"coda"` | Issuer (configurable, default `"coda"`). |
| `iat` | Unix timestamp | Token issuance time. |
| `exp` | Unix timestamp | Expiry (`iat + ttl`, default 1 hour). |

## `sign_token()`

```python
def sign_token(
    subject: str,
    private_key_pem: str,
    *,
    issuer: str = "coda",
    ttl: timedelta = timedelta(hours=1),
    key_id: str | None = None,
) -> str:
```

Creates a short-lived JWT signed with the node's RSA private key.

- `subject`: The QPU ID (becomes the `sub` claim).
- `private_key_pem`: PEM-encoded RSA private key.
- `issuer`: The `iss` claim (default: `"coda"`).
- `ttl`: Token lifetime from now (default: 1 hour).
- `key_id`: Explicit `kid` header. Defaults to `subject` if not set.

Returns a compact-serialized JWT string.

### Usage in Webhook Delivery

```python
token = sign_token(
    self._qpu_id,
    self._jwt_private_key,
    key_id=self._jwt_key_id,
)
headers = {"Authorization": f"Bearer {token}"}
```

A fresh token is generated for every webhook request to avoid clock
skew issues with long-running jobs.

### Usage in Reconnect

```python
token = sign_token(
    settings.qpu_id,
    settings.jwt_private_key,
    key_id=settings.jwt_key_id,
)
auth_header = f"Bearer {token}"
```

## `verify_token()`

```python
def verify_token(
    token: str,
    get_public_key: Callable[[str], str | None],
    *,
    issuer: str = "coda",
) -> dict[str, object]:
```

Verifies a JWT by extracting the `kid` header and resolving it to a
public key via the provided callback. Used on the cloud side (and in
tests).

Raises `jwt.InvalidTokenError` if:
- The token is malformed.
- The `kid` header is missing.
- The key ID is unknown.
- Signature verification fails.
- Required claims (`sub`, `iss`, `exp`, `iat`) are missing.

## `verify_token_with_key()`

```python
def verify_token_with_key(
    token: str,
    public_key_pem: str,
    *,
    issuer: str = "coda",
) -> dict[str, object]:
```

Verifies a JWT when the public key is already known (skips `kid`
lookup). Primarily used in tests.

## Constants

| Constant | Value | Description |
|---|---|---|
| `DEFAULT_ISSUER` | `"coda"` | Default `iss` claim. |
| `DEFAULT_TTL` | `1 hour` | Default token lifetime. |
| `KEY_SIZE` | `2048` | RSA key size in bits. |
