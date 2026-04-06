---
name: update-changelog
description: Add an entry to CHANGELOG.md for a new version.
disable-model-invocation: true
argument-hint: [version]
---

# Update Changelog

Add a new entry to `CHANGELOG.md` for the given version.

## Steps

1. Read `CHANGELOG.md`.
2. Review recent commits since the last tagged release with `git log`.
3. Add a new `## [x.y.z] - YYYY-MM-DD` section below the header, above the previous entry.
4. Summarise changes concisely under `### Added`, `### Changed`, `### Fixed`, or `### Removed` subsections as appropriate.
5. Follow the existing style — short bullet points, no links.

## Arguments

`/update-changelog 0.3.0` — the version string to use in the heading. If omitted, ask the user.
