# 0058 — A rule that refuses a write lives in the application

Whether a write is allowed is decided in one application function that raises a typed error; the database stores data and states facts about a row, and never decides.

## Rules

- The refusal lives in the service that owns the concept, raises the project's typed error, and is reached by every caller — because the HTTP boundary maps a typed error to a status code and has no mapping for a `DatabaseError`, which arrives as a 500 and aborts the surrounding transaction.
- Declarative constraints are not enforcement of this kind and belong in the schema: `CHECK`, `UNIQUE`, `NOT NULL`, foreign keys and `on_delete`. Each states a fact about one row that is true for every writer, costs nothing at admin time, and is visible in the model beside the field it constrains.
- A rule that needs to compare the old row to the new one, or to consult another table, is a business rule. It lives in a service function, with a test that calls that function.
- When a bulk write bypasses the service that owns the rule, the bulk write is the defect. Fix the call site so it goes through the service, or state the rule in the query itself where the caller is an operator script. Never add a mechanism underneath that stops the operator.
- Immutability is a property of the writers, proven by a test that no writer mutates the row. It is not a property to be installed beneath them.

## Do not

- **A trigger, rule or stored procedure that raises on UPDATE or DELETE** — it fires for the maintainer running a data fix and for the restore script as readily as for the bug it was aimed at, it must be dropped and recreated by hand on every server before any bulk correction, and the row it guards can no longer be deleted even when the model holding it is retired.
- **Enforcing one refusal in both the application and the database** — two implementations of one rule (ADR 0039), and the pair drift: this codebase defined `protect_stock_cost()` twice, in two migrations, with two different conditions and two different messages.
