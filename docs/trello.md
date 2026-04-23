# Trello reference

Quick reference for the board this project tracks work on. The board and column layout change rarely; IDs are stable across sessions. If the MCP reports anything different from what's here, this file is out of date — re-fetch with `mcp__trello__get_active_board_info`, `get_lists`, `get_board_labels` and update.

## Board

- Name: **Jobs Manager: Next 2 weeks**
- URL: https://trello.com/b/pur8oyyN
- ID: `68b4da6ff642f4bc1d67499c`
- Workspace ID: `68b4da6ff642f4bc1d674983`

## Lists (columns)

Workflow flow is left → right. When creating a new card with `add_card_to_list`, the usual entry point for a fresh ticket is "Improvements Requested (unrefined)".

| List | ID |
| --- | --- |
| Improvements Requested (unrefined) | `68b4da6ff642f4bc1d6749e5` |
| Approved for next (refined) | `68b4da9fe7e429782e79446d` |
| Bugs spotted in Production | `68c74e343b6910491a437192` |
| Coding standards (REMINDER) | `68b4da7e1969068daa5fc0c5` |
| Doing | `68b4da6ff642f4bc1d6749e6` |
| Testing required | `68b4da7b2c6d34588244b2c9` |
| Needs Cindy to review | `68b6676a66496b11ed849fe9` |
| Done (test then close) | `68b4da6ff642f4bc1d6749e7` |
| Incomprehensible Tickets | `68d8c3f8b5c72f77d1cbe5bc` |

## Labels

Pass these IDs in the `labels` array on `add_card_to_list` / `update_card_details`.

| Label | Colour | ID |
| --- | --- | --- |
| Requested by Corrin | orange | `68b4da6ff642f4bc1d6749e0` |
| Requested by Cindy | green | `68b4da6ff642f4bc1d6749de` |
| Requested by Alex | yellow | `68b4da6ff642f4bc1d6749df` |
| Requested by Miguel | red | `68b4da6ff642f4bc1d6749e1` |
| Feature Request | purple | `68b4da6ff642f4bc1d6749e2` |
| Tech Debt | blue | `68b4da6ff642f4bc1d6749e3` |
| Testing | sky | `68b6236b1cf9282eff67630e` |
| Next release | lime | `68baf415743d4318d267875f` |

## Linking cards to GitHub PRs

Paste the Trello card URL into the PR description and GitHub's Trello Power-Up attaches the card automatically — no manual step on the Trello side.
