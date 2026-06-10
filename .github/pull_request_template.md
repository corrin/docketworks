## 📝 Description

_Short explanation of what you’ve built and why._

## 🔗 Related Jira Work Item

Jira: KAN-123

Use the uppercase Jira key (`KAN-123`) in the PR title or body so GitHub for
Jira links the development event. Jira Automation owns the transition to Done
when the PR is merged.

## 🚀 Changes

- Bullet-list of feature additions or fixes (e.g. extracted `useChat` composable, split `ChatHistory` and `ChatInput` components, added Pinia store).
- …

## ✅ Checklist

**Vue.js (Composition API)**

- [ ] Used Composition API (`<script setup>` & composables), no heavy logic in templates
- [ ] UI logic extracted to reusable composables (`useChat`, etc.)
- [ ] Components are focused & small (<200 LOC)
- [ ] Communication via `props` and `emit`, no direct parent/child ref duplication
- [ ] State management in Pinia; no ad-hoc reactive globals
- [ ] Routes/components lazy-loaded where appropriate

**Quality & Formatting**

- [ ] Passes Prettier (`npx prettier --check .`)
- [ ] Passes ESLint with zero warnings (`npx eslint . --ext .js,.ts,.vue`)
- [ ] Added JSDoc comments for all props and emitted events
- [ ] New or updated unit/E2E tests included

**Definition of Done**

- [ ] Browser JavaScript console checked for relevant warnings/errors
- [ ] Django/server console checked for relevant warnings/errors
- [ ] Build, type-check, schema, and OpenAPI warnings reviewed; no new unexplained warnings
- [ ] Weak frontend typing such as avoidable `any` or loose passthrough types reviewed
- [ ] Affected business workflow regression-tested
- [ ] User-facing workflow still makes sense for the relevant business user

See [docs/jira-usage.md#required-checks](docs/jira-usage.md#required-checks).
