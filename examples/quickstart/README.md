# Hermes Dreaming quickstart fixture

This directory is a tiny offline demo workspace. It is safe to inspect and run without any API key.

## What lives here

- `live/` is the baseline workspace the demo will update.
- `sources/` contains the `DREAM:` markers that drive the offline provider.

The offline-marker provider reads those markers directly, so the fixture works with the default provider and no API key or external model access.
If the `dreaming` entrypoint is not installed yet, use `python -m hermes_dreaming` with the same arguments.
The walkthrough sets `HERMES_DREAMING_STATE_ROOT` to a temp directory so the demo does not touch your normal Dreaming run ledger.

For the exact review -> diff -> validate -> apply -> status walkthrough, see `docs/quickstart.md`.
