"""The fake Xero an E2E iteration run is pointed at (ADR 0060).

It sits at the SDK's transport seam and answers every call from
``FakeXeroObject`` rows with Xero's own wire JSON, so the SDK's deserialiser,
its date ladder and its attribute maps run exactly as they do against the
real tenant. Selected per process by ``settings.XERO_FAKE``; the merge-gate
run never sets it.
"""
