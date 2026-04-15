# Server Setup: --no-cert flag + instance --fqdn support

**Goal:** Allow `server-setup.sh` to skip SSL cert acquisition, and allow `instance.sh create` to configure nginx for a custom FQDN so cutover day is just: point DNS + one certbot command.

**Context:** `server-setup.sh` was written for UAT and unconditionally gets a `*.docketworks.site` wildcard cert. MSM prod uses `office.morrissheetmetal.co.nz` — that cert can only be obtained via HTTP-01 after DNS cutover, so we skip SSL today and configure the instance with the right FQDN now so nginx is ready.

**Implemented in:** PR #147 (`fix/server-setup-iptables`)

**Cutover day:**
```bash
# 1. Point office.morrissheetmetal.co.nz DNS → this server's public IP
# 2. Wait for propagation, then:
sudo certbot --nginx -d office.morrissheetmetal.co.nz
```

## Changes Made

- `scripts/server/server-setup.sh` — added `--no-cert` flag; wraps Dreamhost/certbot/SSL blocks; base nginx config is HTTP-only when `--no-cert` used
- `scripts/server/instance.sh` — added `--fqdn <hostname>` flag; saves `.fqdn` per instance; nginx install block skips reload if cert not yet present
- `scripts/server/templates/nginx-instance.conf.template` — replaced `__INSTANCE__.__DOMAIN__` with `__FQDN__`, `__DOMAIN__` in cert paths with `__CERT_DOMAIN__`
