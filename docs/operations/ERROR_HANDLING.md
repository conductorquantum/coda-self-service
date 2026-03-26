# Error Handling

All domain-specific exceptions inherit from `CodaError` so callers can
distinguish expected operational errors from unexpected bugs with a
single `except CodaError` clause.

## Exception Hierarchy

```
CodaError
├── ConfigError
├── AuthError
├── VPNError
│   └── NodeError
├── ExecutorError
└── WebhookError
```

## Exception Types

### `CodaError`

Base exception for all coda-node errors. Catch this to handle
any expected operational error.

```python
from coda_node import CodaError
```

### `ConfigError`

Invalid or missing configuration.

**Raised when:**
- A persisted config or key file has wrong permissions (not `0600`).
- The persisted config file doesn't contain a JSON object.

**Raised in:** `server/config.py`

### `AuthError`

JWT authentication failure.

**Raised when:** JWT signing or verification fails.

**Raised in:** `server/auth.py` (reserved for future use — current JWT
errors surface as `jwt.InvalidTokenError`).

### `VPNError`

VPN tunnel or health check failure.

**Raised when:** VPN connectivity checks fail.

**Raised in:** `vpn/guard.py`

### `NodeError`

Node provisioning or reconnect failure. Subclass of `VPNError`.

**Raised when:**
- The node token is empty.
- The connect HTTP request fails (after retries).
- The cloud returns a 4xx error.
- The connect response is missing required fields.
- The VPN profile contains dangerous directives.
- The OpenVPN binary is not found.
- The OpenVPN daemon fails to start.
- The VPN tunnel doesn't appear within the timeout.
- VPN is required but no profile is available.

**Raised in:** `vpn/service.py`

### `ExecutorError`

Executor loading or job execution failure.

**Raised when:**
- `CODA_EXECUTOR_FACTORY` has an invalid format (not `module:attr`).
- The imported target is not callable.
- The factory doesn't return an object with a `.run` method.

**Raised in:** `server/executor.py`

### `WebhookError`

Webhook delivery failure.

**Raised when:** Webhook-related errors (reserved for future use —
current webhook errors surface as `httpx.HTTPStatusError` or
`httpx.TransportError`).

**Defined in:** `errors.py`

## Import Patterns

From the top-level package:

```python
from coda_node import CodaError
```

From the errors module:

```python
from coda_node.errors import (
    AuthError,
    CodaError,
    ConfigError,
    ExecutorError,
    NodeError,
    VPNError,
    WebhookError,
)
```

## Design Rationale

- `NodeError` inherits from `VPNError` because node provisioning
  failures are most commonly VPN-related (profile provisioning,
  tunnel setup) and callers often want to catch both with a single
  clause.
- Each exception type maps to a specific subsystem, making it easy to
  route errors to the appropriate handler or monitoring system.
