# Keypair Lifecycle

## Generation

### On the Cloud (Self-Service)

During `buildSelfServiceResponse()`, the cloud generates a fresh
RS256 keypair using Node.js `crypto.generateKeyPairSync()`:

```typescript
const { privateKey, publicKey } = generateKeyPairSync("rsa", {
    modulusLength: 2048,
    publicKeyEncoding: { type: "spki", format: "pem" },
    privateKeyEncoding: { type: "pkcs8", format: "pem" },
});
```

The key ID follows the format `qpu-{qpuId}-{timestamp}`.

The **public key** is stored in the cloud's `jwt_keys` table.
The **private key** is returned to the node in the connect response and
never stored on the cloud.

### On the Node (Testing)

`generate_keypair()` in `auth.py` generates a local keypair for
testing:

```python
keypair = generate_keypair("my-qpu")
# keypair.private_key_pem, keypair.public_key_pem, keypair.key_id
```

This is not used in production — the cloud generates and distributes
keypairs during self-service provisioning.

## Storage

### Cloud Side

The public key is stored in the `jwt_keys` table:

| Column | Value |
|---|---|
| `id` | Auto-generated UUID (used as the device's `jwt_key_id` FK). |
| `key_id` | The logical key ID string (e.g. `qpu-my-qpu-1710000000000`). |
| `public_key` | PEM-encoded RSA public key. |
| `revoked_at` | `NULL` for active keys, ISO timestamp when revoked. |

### Node Side

The private key is persisted to `/tmp/coda-private-key` with `0600`
permissions (see [credential-persistence.md](../self-service/credential-persistence.md)).

The key ID is stored in `/tmp/coda.config` as `jwt_key_id`.

## Rotation

Key rotation happens automatically during re-provisioning:

1. A new keypair is generated.
2. The new public key is inserted into `jwt_keys`.
3. The device's `jwt_key_id` FK is updated to point to the new key.
4. The previous key is revoked (`revoked_at = now()`).

Revoked keys remain in the database for audit purposes but are not
used for verification.

## Reconnect

During JWT reconnect, the cloud:

1. Verifies the JWT signature against the public key referenced by the
   device's `jwt_key_id`.
2. Does **not** issue a new private key — the node continues using its
   persisted key.

The connect response includes `jwt_key_id` (but not
`jwt_private_key`) on reconnect so the node can confirm it is using
the correct key.

## Security Properties

- The private key is generated on the cloud and transmitted to the
  node exactly once during self-service. It is never stored on the
  cloud.
- The private key is stored on the node's filesystem with `0600`
  permissions and validated on read.
- Key rotation happens atomically — the old key is revoked only after
  the new key and device update succeed.
- If provisioning fails (e.g. VPN provisioning fails), the newly
  created key is deleted to prevent stale credential leaks.
