# JWT Authentication

All communication between the node and the Coda cloud is authenticated
with RS256 JWTs. The node signs tokens with its private key; the cloud
verifies them with the corresponding public key registered during
node provisioning.

## Topics

| Document | Summary |
|---|---|
| [SIGNING.md](SIGNING.md) | Token creation, claims, headers, and verification. |
| [KEYPAIR_LIFECYCLE.md](KEYPAIR_LIFECYCLE.md) | Key generation, storage, rotation, and revocation. |

## Key Files

| File | Role |
|---|---|
| `src/coda_node/server/auth.py` | `sign_token()`, `verify_token()`, `verify_token_with_key()`, `generate_keypair()`, `KeyPair`. |

## Where JWTs Are Used

| Context | Signer | Verifier | Purpose |
|---|---|---|---|
| Webhook delivery | Node (`sign_token`) | Cloud | Authenticate job results. |
| Reconnect handshake | Node (`sign_token`) | Cloud | Authenticate JWT-based reconnect. |
| Heartbeat | Node (`sign_token`) | Cloud | Authenticate periodic heartbeats. |

The node never verifies inbound JWTs in production — `verify_token()`
and `verify_token_with_key()` exist for testing and potential future
inbound auth scenarios.
