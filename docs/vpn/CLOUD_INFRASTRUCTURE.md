# Cloud VPN Infrastructure

The Coda cloud provisions per-QPU VPN credentials during the connect
handshake using AWS Client VPN with mutual TLS authentication. This
document describes the cloud-side architecture that the node interacts
with.

## Architecture

The VPN infrastructure consists of:

- **AWS Client VPN Endpoint** — mutual TLS authentication, split tunnel
  enabled, CloudWatch connection logging.
- **Certificate Authority** — initialized via Easy-RSA, stored in AWS
  Secrets Manager (`coda-{env}-vpn-ca`).
- **Server certificate** — generated during endpoint provisioning,
  imported to ACM.
- **Per-QPU client certificates** — generated at connect time using
  `node-forge`, imported to ACM.

## Per-Init VPN Identity

VPN credentials are bound to a per-init identity, not just the static
`qpu_id`. The identity is derived as:

```
identity_hash = sha256("{qpuId}:{clientIdentity}")[0:16]
```

Where `clientIdentity` is:
- `machine_fingerprint` if the client sends one (recommended).
- The generated JWT key ID otherwise.

This means two different self-service attempts for the same QPU (e.g.
from different physical machines) receive separate VPN credentials.

## Certificate Issuance Flow

When `generateVpnProfile()` is called during connect:

1. **Check environment** — returns `null` if `VPN_ENVIRONMENT` is unset
   (VPN not configured for this deployment).
2. **Look up existing cert** — checks Secrets Manager for
   `coda-{env}-vpn-client/{qpuId}/{identityHash}`.
3. **If exists and complete** (has cert, key, and non-`"pending"` ACM
   ARN) — returns the existing cert.
4. **Load CA** — fetches `coda-{env}-vpn-ca` for the signing key.
5. **Generate client cert** — 2048-bit RSA, CN =
   `{qpuId}-{identityHash}`, 128-bit random serial (ACM-safe positive
   integer), SHA-256 signed, 10-year validity.
6. **Atomic claim** — uses `CreateSecretCommand` to atomically claim
   the secret slot. Only one concurrent caller succeeds.
7. **ACM import** — imports the cert to ACM for lifecycle visibility.
8. **Update secret** — replaces the `"pending"` ACM ARN with the real
   one.
9. **Assemble profile** — exports the base Client VPN config from EC2,
   appends `<cert>` and `<key>` blocks.

### Concurrent Issuance

The `CreateSecretCommand` acts as a distributed lock:

- **Winner**: Proceeds to ACM import, updates secret with real ARN.
- **Losers**: Read the winner's cert from Secrets Manager.
- **ACM import failure**: Placeholder secret is deleted so retries
  can succeed.

This prevents orphaned ACM certificates from concurrent issuance.

## Profile Assembly

The final `.ovpn` profile combines:

```
<base Client VPN config from EC2>

<cert>
<PEM client certificate>
</cert>

<key>
<PEM client private key>
</key>
```

The profile is base64-encoded internally but decoded to plaintext
before being returned in the connect response (via
`decodeProfileIfBase64()`).

## AWS Secrets

| Secret Name | Contents |
|---|---|
| `coda-{env}-vpn-config` | Operator-supplied: `vpc_id`, `subnet_ids`, `target_cidr` (required), `dns_server`. |
| `coda-{env}-vpn-ca` | CA certificate and private key. |
| `coda-{env}-vpn-server` | Server certificate, private key, and ACM ARN. |
| `coda-{env}-vpn-state` | Client VPN endpoint ID and metadata. |
| `coda-{env}-vpn-client/{qpuId}/{hash}` | Client cert bundle (cert, key, ACM ARN, metadata). |

## Security Properties

- VPN credentials are **never stored in self-service tokens** — they
  are provisioned at connect time only.
- VPN credentials are **never returned from token CRUD APIs** — they
  are stripped from both persistence and API responses.
- `acm:ExportCertificate` is **intentionally excluded** from IAM
  policies — prevents CA private key exposure through ACM.
- `target_cidr` is **mandatory** — the setup script refuses to default
  to `0.0.0.0/0`.
- **Split tunnel** is enabled — only traffic for `target_cidr` routes
  through the VPN.

## Node-Side Interaction

The node receives the `.ovpn` profile in `vpn.client_profile_ovpn` of
the connect response and:

1. Validates it against dangerous directives (see
   [tunnel-lifecycle.md](tunnel-lifecycle.md)).
2. Writes it to disk with `0600` permissions.
3. Launches an OpenVPN daemon.
4. Waits for the tunnel interface to appear.

The node does not interact with AWS services directly — all VPN
provisioning happens on the cloud side during the connect handshake.
