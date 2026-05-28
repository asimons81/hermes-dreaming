# Hermes Dreaming v0.1.1 Release Notes (Draft)

Status: release candidate review only, not published.

## What changed since v0.1.0

- Real review diffs: `dreaming diff` now shows unified diffs against `--live-root` or the artifact workspace root instead of only dumping the staged report.
- Safer apply: artifact apply now preflights selected proposals, snapshots touched files up front, rolls back on write or verification failure, and persists audit fields.
- Better audit trail: artifacts now record apply start and finish timestamps, applied proposal ids, backup paths, validation errors, and apply errors.
- Offline quickstart: `examples/quickstart/` plus `docs/quickstart.md` gives users a no-API-key review -> diff -> validate -> apply -> status demo.
- Cleaner tests and demos: pytest isolates Dreaming state, and `HERMES_DREAMING_STATE_ROOT` lets quickstart/demo runs avoid the real `~/.hermes/dreaming` run ledger.
- Safe updates: `dreaming update` supports fast-forward plugin updates with dirty-tree protection and optional pytest verification.
- Plugin packaging: the repo installs as the `hermes-dreaming` Hermes plugin and bundles the Dreaming skill.

## Packaging and versioning

- Package version: `0.1.1`
- `src/hermes_dreaming/__init__.py` exports `__version__ = "0.1.1"`
- `pyproject.toml` pins `version = "0.1.1"`
- `CHANGELOG.md` has a dedicated `0.1.1` section

## Verification run

Commands executed during release prep:

- `git diff --check`
- `python -m pytest -q`
- `python -m build --wheel`

Results:

- `git diff --check` passed cleanly
- `pytest` passed: 60 tests
- wheel build passed: `hermes_dreaming-0.1.1-py3-none-any.whl`

## Release readiness verdict

Technically ready for tagging and publishing from a build/test/docs standpoint.

Operational gate still applies: do not tag or publish until Tony explicitly approves the release.
