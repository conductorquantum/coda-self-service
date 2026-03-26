---
name: update-docs
description: Keep docs/ and README.md in sync with source code changes. Use after modifying source files to update affected documentation.
---

Keep `docs/` and `README.md` in sync with source code changes.

## Documentation layout

The `docs/` directory is organized into feature-area subdirectories.
Discover the current structure by reading `docs/INDEX.md` and listing
subdirectories — do not assume a fixed set of areas or files.

Each feature area follows this pattern:

```
docs/<area>/
├── INDEX.md          # Overview, topics table, key source files, cloud counterparts
├── <topic-a>.md
└── <topic-b>.md
```

`docs/INDEX.md` is the top-level entry point linking to all areas.
`README.md` is the user-facing quickstart (not a duplicate of `docs/`).

## Conventions

- Each feature area has its own subdirectory with an `INDEX.md`.
- `INDEX.md` files contain: overview, topics table, key source files table, and cloud counterparts (if any).
- Topic files document: purpose, API/format details, code references, and cross-links.
- Use "node" (not "bootstrap" or "self-service") for provisioning terminology.
- External identifiers from other codebases keep their original names with a "(cloud-side naming)" annotation.

## How to update

1. **Read the staged diff** (`git diff --cached`) to identify which source files changed and what behavior was added/modified/removed.
2. **Discover affected docs**: read `docs/INDEX.md` to understand the current areas, then find the doc files that cover the changed source files. Look at existing cross-references and `INDEX.md` "Key Files" tables to map source → docs.
3. **Read the affected doc files** and compare against the new source behavior.
4. **Update docs** to reflect changes: signatures, config fields, env vars, error types, endpoints, sequence diagrams, etc.
5. **Update `README.md`** if the change affects quickstart, configuration, CLI, endpoints, or error handling.
6. **Update `docs/INDEX.md`** if you add/remove/rename a feature area or the source layout changes.
7. **Print a short summary** of what was updated and why.

## Rules

- Do NOT assume a fixed file/directory structure — always discover it.
- Do NOT create new feature subdirectories without clear justification.
- Do NOT add speculative documentation for unimplemented features.
- Keep doc files concise — describe behavior, not implementation details line-by-line.
- Every doc file must have a `# Title` and be linked from its area's `INDEX.md`.
- If no docs need updating (e.g. test-only changes, formatting), say so and exit.
