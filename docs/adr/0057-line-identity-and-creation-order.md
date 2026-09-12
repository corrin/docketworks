# 0057 — Line identity and creation order

Persisted line items have permanent IDs and a server-defined creation order shared by every reader.

## Rules

- Retain UUID primary keys for PO lines, cost lines and timesheet entries. APIs, grid keys and mutations identify saved rows by UUID; row positions are presentation only.
- Record an immutable creation timestamp when a new line is persisted. Timestamps need not be unique: sort creation time ascending, then UUID ascending, within the list's business groups.
- Keep cost groups material, adjustment, then time, and timesheet groups by staff and accounting day. Timesheet `entry_seq` remains stored metadata, not the display order.
- Define the ordering at the model and use it in collection APIs, document line lists and integration payloads. Frontends preserve the server's order, including after saved edits and reloads.
- A creation timestamp is never nullable. Where history did not record one, a one-off migration sets the best value available — normally the parent record's own creation time — and the column is `NOT NULL` from that migration onward (ADR 0059). An approximate time every reader can sort by beats an accurate absence every reader must special-case.
- Apply stable identity and explicit ordering to new persisted list-item models. Keep IDs and timestamps out of ordinary entry controls.

## Do not

- **Use a timestamp as a primary key or force it to be unique** — a batch can legitimately share a timestamp.
- **Infer history from UUID order** — UUIDs break ties consistently but do not recover lost insertion order.
- **Rank a list by a value instead of by creation order** — newest-first, or largest-quantity-first, reads as helpful and means two screens showing the same rows disagree about which is first. Rank in the query that needs it, never in the model's ordering.
