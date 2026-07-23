# DocketWorks Frontend

This repository contains the Vue 3 front‑end for the DocketWorks application.
It communicates with the Django backend in the repository root.

## Getting Started

Install dependencies and run the development server:

```bash
npm install
npm run dev
```

The app expects the backend to run at `http://localhost:8000`.

### Running with Tunnels (Remote Access)

For remote access during development, use the single ngrok tunnel (Vite proxies `/api` to Django):

```bash
ngrok http 5173 --domain=<your-ngrok-domain>
```

Monitor requests at: http://localhost:4040

## Project Structure

Source files live in the `src/` directory:

- **assets/** – Tailwind CSS and static assets
- **components/** – Reusable Vue components
- **composables/** – Reusable logic (Composition API functions)
- **lib/** – Utility helpers
- **plugins/** – Plugins such as Axios configuration
- **router/** – Vue Router setup
- **schemas/** – Zod schemas for API responses
- **services/** – API service wrappers
- **stores/** – Pinia stores for state management
- **types/** – TypeScript interfaces
- **views/** – Page‑level Vue components

## Additional Documentation

See `docs/overview.md` for a newcomer‑oriented explanation of the codebase.
