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
│   └── SelfServiceError
├── ExecutorError
└── WebhookError
```

## Exception Types

### `CodaError`

Base exception for all coda-self-service errors. Catch this to handle
any expected operational error.

```python
from self_service import CodaError
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

### `SelfServiceError`

Self-service provisioning or reconnect failure. Subclass of `VPNError`.

**Raised when:**
- The self-service token is empty.
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
from self_service import CodaError
```

From the errors module:

```python
from self_service.errors import (
    AuthError,
    CodaError,
    ConfigError,
    ExecutorError,
    SelfServiceError,
    VPNError,
    WebhookError,
)
```

## Design Rationale

- `SelfServiceError` inherits from `VPNError` because self-service
  failures are most commonly VPN-related (profile provisioning,
  tunnel setup) and callers often want to catch both with a single
  clause.
- Each exception type maps to a specific subsystem, making it easy to
  route errors to the appropriate handler or monitoring system.
