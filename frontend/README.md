# React + TypeScript + Vite

This template provides a minimal setup to get React working in Vite with HMR and some Oxlint rules.

Currently, two official plugins are available:

- [@vitejs/plugin-react](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react) uses [Oxc](https://oxc.rs)
- [@vitejs/plugin-react-swc](https://github.com/vitejs/vite-plugin-react/blob/main/packages/plugin-react-swc) uses [SWC](https://swc.rs/)

## React Compiler

The React Compiler is not enabled on this template because of its impact on dev & build performances. To add it, see [this documentation](https://react.dev/learn/react-compiler/installation).

## Linting

The frontend uses Oxlint with `oxlint-tsgolint` for type-aware TypeScript rules. Run it with `npm run lint`.

TypeScript 7.0 does not expose the compiler API required by `typescript-eslint`. Once `typescript-eslint` supports the native TypeScript 7 compiler API, replace the Oxlint setup with its type-aware recommended configuration.
