# Integration Scripts

Operator-run checks for live integrations. These scripts may create or mutate
real data in external systems and are not part of the default test suite.

Use them for incident investigation, pre-deploy smoke checks, and periodic
verification of third-party contracts.

Guidelines:

- App behavior must be exercised through public app HTTP APIs.
- External systems may be verified through their official SDK/API readbacks.
- Do not use Django internals, DRF test clients, fake providers, or hidden
  request-environment overrides for app-side behavior.
- Keep setup explicit in the script header and logs.

Available checks:

- `verify_xero_batch_order.py`: verifies Xero preserves `create_contacts`
  response order for bulk contact creation.
- `verify_xero_client_quote_contract.py`: creates a client/job/quote through
  the public app API and verifies Xero persisted the contact fields and quote
  contact reference.
