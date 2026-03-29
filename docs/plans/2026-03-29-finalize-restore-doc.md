# Plan: One restore doc for all environments

## Context

The restore process is the same on dev and UAT. The restore doc should be environment-agnostic: assume venv active, .env loaded, in the project root (which is `~/code/` on UAT, the repo root on dev). All paths relative — `logs/`, `restore/` — work identically in both.

## Directory alignment

Remove `code/` subdirectory on UAT. The git checkout IS the instance home dir, same as dev where the project root is the working dir. Everything lives at the same level:

```
~/                          (= project root, = git checkout)
├── .env                    (gitignored)
├── .bash_profile
├── .venv → symlink
├── credentials.env         (gitignored — add to .gitignore)
├── gcp-credentials.json    (gitignored — add to .gitignore)
├── gunicorn.sock           (gitignored — add to .gitignore)
├── manage.py
├── apps/
├── frontend/
├── logs/                   (gitignored — already)
├── restore/                (gitignored — already)
├── mediafiles/             (gitignored — add to .gitignore)
├── staticfiles/            (gitignored — add to .gitignore)
├── dropbox/                (gitignored — add to .gitignore)
└── ...
```

All paths relative — `logs/`, `restore/`, `manage.py` — work identically on dev and UAT.

### Changes to `scripts/server/instance.sh`
- Clone repo directly into `$INSTANCE_DIR` instead of `$INSTANCE_DIR/code`
- Create `logs/`, `mediafiles/`, `staticfiles/`, `dropbox/` inside the repo dir
- `.bash_profile` simplifies: just activate venv and source .env (already in home dir)
- Update gunicorn template: working dir is `$INSTANCE_DIR` not `$INSTANCE_DIR/code`

### Changes to `.gitignore`
Add: `credentials.env`, `gcp-credentials.json`, `gunicorn.sock`, `mediafiles/`, `staticfiles/`, `dropbox/`

### Changes to templates
- `gunicorn-instance.service.template` — update WorkingDirectory
- `nginx-instance.conf.template` — update static/media paths (no `code/` prefix)

## 1. Rename and rewrite `docs/restore-to-dev.md` → `docs/backup-restore.md`

- Drop "to-dev" from the name
- Remove all environment-specific content: Windows/PowerShell, ngrok, Vite dev server, VS Code, "skip for UAT" annotations
- Assume: venv active, .env loaded, in the project dir
- All paths relative: `restore/`, `logs/`
- Add missing steps: verify migrations, run_scheduler, test_serializers, test_kanban_api, Playwright tests
- Keep: the core restore steps, checks, and Xero setup sequence

## 2. Delete `docs/instance-setup-uat.md`

The restore doc covers everything. UAT has no additional steps that belong in a separate doc.

## 3. Update references

- `docs/xero_setup.md` — update reference from restore-to-dev.md
- `docs/server_setup.md` — update reference
- `apps/job/management/commands/backport_data_restore.py` — update reference

## Files to modify
- `docs/restore-to-dev.md` → rename to `docs/backup-restore.md`, rewrite
- `docs/instance-setup-uat.md` — delete
- `docs/xero_setup.md` — update reference
- `docs/server_setup.md` — update reference
- `apps/job/management/commands/backport_data_restore.py` — update reference
