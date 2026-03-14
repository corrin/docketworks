# Good Practices – Jobs Manager Frontend

## SOLID Principles

- **Single Responsibility Principle (SRP):** Each module, class, or function should have one responsibility only.
- **Open/Closed Principle (OCP):** Code should be open for extension, but closed for modification.
- **Liskov Substitution Principle (LSP):** Subtypes must be substitutable for their base types without breaking the application.
- **Interface Segregation Principle (ISP):** Prefer small, specific interfaces over large, general ones.
- **Dependency Inversion Principle (DIP):** Depend on abstractions, not on concrete implementations.

## Avoid Deep Nesting

- Limit code nesting to a maximum of 2-3 levels.
- Use early returns to reduce indentation and improve readability.
- Refactor complex logic into smaller, well-named functions.

## Prefer Switch-Case Over Multiple Ifs

- When handling multiple conditions on the same variable, use `switch-case` instead of chained `if-else` blocks.
- This improves clarity and makes it easier to add or modify cases.

```typescript
// Prefer this:
switch (status) {
  case 'draft':
    // ...
    break
  case 'active':
    // ...
    break
  default:
  // ...
}

// Instead of:
if (status === 'draft') {
  // ...
} else if (status === 'active') {
  // ...
} else {
  // ...
}
```

## Objects Calisthenics

- Only one level of indentation per method.
- Don't use the `else` keyword (prefer early returns).
- Wrap all primitives and strings (use value objects where possible).
- First class collections (never expose raw arrays or objects).
- One dot per line (avoid chaining too many calls).
- Don't abbreviate (use clear, descriptive names).
- Keep all entities small (classes, functions, files).

## Clean Code

- Write code for humans, not just for machines.
- Use meaningful names for variables, functions, and classes.
- Keep functions and files short and focused.
- Remove dead code and unnecessary comments.
- Prefer composition over inheritance.
- Avoid magic numbers and hardcoded values.
- Write self-explanatory code; comments should explain "why", not "what".

## Clean Architecture

- Separate concerns: UI, business logic, and data access should be in distinct layers.
- Use dependency injection for services and repositories.
- Keep business logic independent from frameworks and UI.
- Favor composition and modularity for testability and maintainability.
- Use boundaries (interfaces, adapters) to decouple layers.

---

**References:**

- [SOLID Principles](https://en.wikipedia.org/wiki/SOLID)
- [Object Calisthenics](https://williamdurand.fr/2013/06/03/object-calisthenics/)
- [Clean Code (Robert C. Martin)](https://www.oreilly.com/library/view/clean-code/9780136083238/)
- [Clean Architecture (Robert C. Martin)](https://www.oreilly.com/library/view/clean-architecture/9780134494272/)
