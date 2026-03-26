---
name: read-docs
description: Gather context from docs/ before implementing or modifying a feature. Use when starting work on a feature, investigating how something works, or onboarding to the codebase.
---

Gather context from `docs/` before implementing or modifying a feature.

## How to use

1. **Start at `docs/INDEX.md`** — read it to discover all feature areas and the source layout.
2. **Navigate to the relevant area** — open the area's `INDEX.md` to see its topics, key source files, and cloud counterparts.
3. **Read the topic files** that relate to your task for detailed behavior, API formats, config fields, sequence diagrams, and cross-references.
4. **Check `README.md`** for user-facing quickstart, CLI flags, configuration tables, and endpoint summaries.

## Tips

- Area `INDEX.md` files list the source files that implement each feature — use these to locate code quickly.
- Cross-links between topic files connect related concepts (e.g. auth ↔ node ↔ VPN).
- Cloud counterpart tables (where present) point to the corresponding cloud-side files and endpoints.
- If a doc file references a config field or env var, the full reference is in the `configuration/` area.
