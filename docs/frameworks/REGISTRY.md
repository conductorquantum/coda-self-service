# Auto-Discovery

When `CODA_EXECUTOR_FACTORY` is not set, the runtime automatically
scans installed Python packages for executor factories that follow the
naming convention.

## Convention

Backend packages expose a factory at:

```
<package>.executor_factory:create_executor
```

For example, a backend package `coda-acme` would provide
`coda_acme.executor_factory:create_executor`.

## Discovery Process

`_discover_executor_factories()` in `executor.py`:

1. Lists all importable top-level Python packages via
   `importlib.metadata.packages_distributions()`.
2. Skips internal packages (`self_service`, private `_`-prefixed
   packages, and sub-packages with dots).
3. For each candidate, checks whether `<pkg>.executor_factory` exists
   using `importlib.util.find_spec()` (cheap filesystem check, no
   import).
4. If the module exists, imports it and checks for a callable
   `create_executor` attribute.
5. Collects all matches as `module:attr` import paths.

## Resolution Rules

| Matches | Behavior |
|---|---|
| 0 | Log a warning; fall back to `NoopExecutor`. |
| 1 | Log an info message; use the discovered factory. |
| 2+ | Log a warning listing all candidates; fall back to `NoopExecutor`. Set `CODA_EXECUTOR_FACTORY` explicitly to resolve. |

## Explicit Override

`CODA_EXECUTOR_FACTORY` always takes precedence over discovery.  When
set, the runtime skips the scan entirely and imports the specified
factory directly.

```bash
export CODA_EXECUTOR_FACTORY="coda_acme.executor_factory:create_executor"
```

## Performance

Discovery runs once at startup.  The `find_spec()` check is a
lightweight filesystem lookup that does not import the package.  Only
packages where the `executor_factory` module actually exists are
imported.
