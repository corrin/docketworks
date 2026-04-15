# Consolidate apt installs in server-setup.sh

**Context:** `server-setup.sh` has 10 separate `apt install` calls. Six are unconditional and can be grouped into one block right after `apt update && apt upgrade -y`. This reduces invocations, runs dependency resolution once, and makes the "what does this script install?" question easy to answer at a glance.

**File:** `scripts/server/server-setup.sh`

---

## Change

Replace the six unconditional install calls with one block immediately after the `apt update && apt upgrade -y` line (line 91):

```bash
log "Installing system packages..."
DEBIAN_FRONTEND=noninteractive apt install -y \
    etckeeper \
    build-essential libpq-dev pkg-config pandoc unzip \
    python3.12 python3.12-venv python3.12-dev \
    git \
    iptables-persistent netfilter-persistent \
    quota
log "System packages installed."
```

Then remove the individual install calls at lines 100, 110, 117, 215, 220, 226, including:
- The `if dpkg -l | grep -q "ii  etckeeper "` guard (apt is idempotent, guard is unnecessary)
- The "Installing build dependencies..." and "Ensuring Python 3.12..." log lines that precede those installs

Keep in place (unchanged):
- All `log_version` calls (they stay where they are, logging after the relevant section)
- The etckeeper post-install check (`if [[ -d /etc/.git ]]`)
- The "Installing quota tools..." log line and quota enable logic (lines 225–234)
- All conditional installs: nodejs (NodeSource), postgresql, nginx, certbot, gh

`DEBIAN_FRONTEND=noninteractive` prevents iptables-persistent from prompting to save current rules during install.

- [x] Apply changes to `scripts/server/server-setup.sh`
- [x] Commit, push, PR (#154)
