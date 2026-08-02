# ngrok Setup

ngrok gives your local environment a public URL. It is **required**, not optional: Xero OAuth
callbacks must land on a public URL that Xero holds, and there is no way to do that from bare
`localhost`.

v2 always serves the **compiled** frontend (`vite preview`) on **:4173**, and that preview proxies
`/api` and `/media` to Django on :8000. So a **single tunnel to :4173** is enough — a callback that
reaches the ngrok domain is proxied through the SPA to the backend. (This differs from v1, which
tunnelled the Vite dev server; v2 has no hot dev server.)

## Choose your developer name

Pick a short name. It becomes part of your ngrok subdomain (and, by convention, your database name):

- ngrok subdomain: `docketworks-<your-name>.ngrok-free.app`
- Database: `docketworks_v2` (or `dw_<your-name>` if you run more than one checkout)

## Set up ngrok

1. Sign up at [ngrok.com](https://ngrok.com/) and install the client.
2. Claim **one** free static domain (e.g. `docketworks-dave.ngrok-free.app`).
3. Copy the config template and fill in your authtoken and domain:

   ```bash
   cp ngrok.yml.example ngrok.yml
   ```

   ```yaml
   version: "2"
   authtoken: <your ngrok authtoken>
   tunnels:
     dev:
       addr: 4173
       proto: http
       domain: docketworks-<your-name>.ngrok-free.app
   ```

   `ngrok.yml` is gitignored — never commit your authtoken.

4. Point the backend at the public domain. In `.env`, set both to your ngrok domain (https):

   ```
   APP_DOMAIN=docketworks-<your-name>.ngrok-free.app
   FRONT_END_URL=https://docketworks-<your-name>.ngrok-free.app
   ```

   `APP_DOMAIN` feeds `ALLOWED_HOSTS` and the cache key prefix; `FRONT_END_URL` is where the backend
   sends links/redirects back to the frontend.

The **"Ngrok Tunnels"** VS Code task runs `ngrok start dev --config ngrok.yml`; it is wired into the
"Start E2E Environment" task (see [development_session.md](development_session.md)).

## Xero

The redirect URI you register in the Xero developer portal is on this ngrok domain. The Xero
integration ports in a later phase; when it lands, register the redirect URI the app reports
(Admin → Xero Apps) and make sure it matches the portal exactly.
