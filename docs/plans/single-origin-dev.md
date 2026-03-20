# Frontend Spec: Single-Origin Development (Vite Proxy)

## Goal

Eliminate the need for two ngrok tunnels in development by adding a Vite dev server proxy. All API and admin requests go through Vite's proxy to Django, making everything same-origin.

## What to change

### 1. Add proxy config to `vite.config.ts`

In the `server` block, add:

```ts
server: {
  // ... existing config ...
  proxy: {
    '/api': {
      target: 'http://localhost:8000',
      changeOrigin: true,
    },
  },
}
```

### 2. Remove `VITE_API_BASE_URL` usage

`client.ts:69-74` already falls back to `window.location.origin` when `VITE_API_BASE_URL` is not set. So:

- Remove `VITE_API_BASE_URL` from any `.env` files
- No code change needed in `client.ts` — the fallback does the right thing

### 3. Auth method

`VITE_AUTH_METHOD` can be `cookie` for both dev and prod. Same-origin means no cross-domain cookie issues, so bearer tokens are no longer needed in dev.

## How dev works after this

1. Start Django: `python manage.py runserver 0.0.0.0:8000`
2. Start Vite: `npm run dev` (serves on port 5173)
3. For external access: `ngrok http 5173 --domain=your-domain.ngrok-free.app`

One tunnel, one domain. Vite serves the frontend and proxies `/api/*` to Django.

## Xero OAuth flow

The Xero OAuth callback (`/api/xero/oauth/callback/`) works through the proxy:

1. User clicks "Connect Xero" → redirected to Xero
2. Xero redirects back to `https://your-domain.ngrok-free.app/api/xero/oauth/callback/`
3. Vite proxy forwards to Django on localhost:8000
4. Django processes the callback and redirects to the frontend URL

No changes needed to the Xero redirect URI configuration.
