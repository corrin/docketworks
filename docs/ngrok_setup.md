# Ngrok Setup

Set up ngrok tunnels for local development. Do this first — you'll need the domain for Xero app configuration.

## Choose Your Developer Name

Pick a short name for yourself. This becomes part of your database name, ngrok subdomain, and Xero app name:

- Database: `dw_<yourname>` (e.g., `dw_dave`)
- Ngrok subdomain: `docketworks-<yourname>.ngrok-free.app`
- Xero App name: `docketworks-<yourname> Development`

## Set Up Ngrok

1. Sign up at [ngrok.com](https://ngrok.com/) and install the client
2. Claim two free static domains — one for backend, one for frontend (e.g., `docketworks-dave.ngrok-free.app` and `docketworks-dave-front.ngrok-free.app`)

That's it. You'll configure the tunnels in your `.env` later during [initial_install.md](initial_install.md).
