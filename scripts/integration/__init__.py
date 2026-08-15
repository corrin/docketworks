"""Operator-run checks for live integrations.

These scripts may create or mutate real data in external systems and are
never part of the default test suite. Use them for incident investigation,
pre-deploy smoke checks, and periodic verification of third-party contracts.

Rules of the directory:

- App behavior is exercised through public app HTTP APIs only.
- External systems are verified through their official SDK/API readbacks.
- No Django test clients, fake providers, or hidden request-environment
  overrides for app-side behavior.
- Keep setup explicit in each script's header and logs.
"""
