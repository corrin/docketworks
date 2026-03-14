## 📝 Description

_Short explanation of what you’ve built and why._

## 🔗 Related Issue

Closes #[issue-number]

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
