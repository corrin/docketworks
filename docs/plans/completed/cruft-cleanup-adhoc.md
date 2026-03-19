# Cruft Cleanup — adhoc/ directory

Most adhoc files are fine as reference examples for interacting with Django.
These four fall short of that bar:

## Delete

- [ ] `mistral_parsing.py` — Self-describes as broken ("THIS FILE NEEDS FIXING. print! error eating!")
- [ ] `ocr_results.json` — 35KB data dump output, not code
- [ ] `ocr_results.md` — 41KB data dump output, not code
- [ ] `generate_curl_command.py` — Dumps live access token, runs via shell=True
