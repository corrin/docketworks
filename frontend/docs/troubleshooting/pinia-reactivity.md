# Pinia Reactivity Pitfall – Destructuring a Store Without `storeToRefs`

When we added the Purchase Orders table we hit a confusing bug:

- The API call returned **116 purchase orders** (confirmed in console logs).
- The Pinia store’s `orders` array **contained the data**.
- The Vue component still rendered **“0 results”**.

It turned out to be a classic Pinia reactivity gotcha.

---

## What happened?

```ts
// ❌ buggy code in PurchaseOrderView.vue
const store = usePurchaseOrderStore()
const orders = store.orders // <- loses reactivity
const loading = store.loading
```

`store.orders` is a **`ref`** inside the store, but when we read it this way we get the _value_ at that moment – not a reactive reference.  
Subsequent updates inside the store no longer reach the component, so the UI never updates.

---

## The fix

```ts
// ✅ correct: keep reactivity with storeToRefs
import { storeToRefs } from 'pinia'

const store = usePurchaseOrderStore()
const { orders, loading } = storeToRefs(store)
```

`storeToRefs` converts every state property of the store into its own `ref`, preserving full reactivity.  
After this change the component reacted immediately and all 116 rows appeared.

---

## How to avoid this bug

| ✅ Do                                                                                                       | ❌ Don’t                                                                                                     |
| ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Use `storeToRefs(store)` when you need individual refs in a component.                                      | Destructure properties directly from the store (`const x = store.x`) unless you never expect them to change. |
| Alternatively, access properties via `store.orders` in the template/composition code without destructuring. | Assume “it worked in Options API” – Pinia re-exports are **not** automatically reactive when pulled out.     |
| Add a quick unit test or console log showing `orders.length` after API calls.                               | Silently ignore console warnings – Vue will often warn about failed renders.                                 |

---

## Quick checklist for future components

1. Need local refs to store state? → **Use `storeToRefs`**.
2. Reading but not mutating? → `const store = useStore(); store.foo` is fine.
3. Mutating store state? → call store actions or mutate refs returned by `storeToRefs`.
4. Seeing “0 results” while logs show data? → Check for this reactivity bug first.

---

## Further reading

- Pinia docs – [“Destructuring the store”](https://pinia.vuejs.org/core-concepts/#destructuring-the-store)
- Vue docs – [Reactivity Fundamentals](https://vuejs.org/guide/essentials/reactivity-fundamentals.html)

---

### TL;DR

> **Always wrap Pinia stores with `storeToRefs` if you plan to destructure their reactive state.**  
> It prevents silent reactivity loss and the “data in store but not on screen” headache.
