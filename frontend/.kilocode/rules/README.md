# Kilo Custom Rules – Jobs Manager Frontend

This directory contains custom rules for Kilo Code AI that define development standards, architecture, and project-specific practices for the Jobs Manager Frontend.

## 📋 Rules Index

### Critical Architectural Rules

- **[01-architectural-separation.md](./01-architectural-separation.md)** – Absolute frontend-backend separation
- **[02-schema-management.md](./02-schema-management.md)** – API schema and type management

### Frontend Development

- **[03-frontend-development.md](./03-frontend-development.md)** – Vue 3 + TypeScript development standards
- **[04-authentication-security.md](./04-authentication-security.md)** – Authentication and security
- **[05-api-integration.md](./05-api-integration.md)** – Django REST API integration
- **[06-state-management.md](./06-state-management.md)** – State management with Pinia
- **[07-component-architecture.md](./07-component-architecture.md)** – Vue component architecture

### Quality and Performance

- **[08-error-handling.md](./08-error-handling.md)** – Error handling and debugging
- **[09-performance-optimization.md](./09-performance-optimization.md)** – Performance optimization
- **[10-project-specific-features.md](./10-project-specific-features.md)** – Project-specific features

### Process and Documentation

- **[11-documentation-standards.md](./11-documentation-standards.md)** – Documentation standards
- **[12-testing-protocols.md](./12-testing-protocols.md)** – Testing protocols
- **[13-backend-coordination.md](./13-backend-coordination.md)** – Backend-frontend coordination
- **[14-good-practices.md](./14-good-practices.md)** – Good practices (SOLID, Clean Code, etc.)

## 🚨 Critical Rules

### Architectural Separation

- **NEVER** put backend logic in the frontend
- **NEVER** put frontend logic in the backend
- **ALWAYS** use auto-generated API schemas
- **PROHIBITED** to create local types for database data

### Mandatory Coordination

- **ALWAYS** coordinate with backend Claude through the user
- **NEVER** assume data structures without confirmation
- **MANDATORY** to validate data ownership (UI vs database)

### Code Quality

- **ALWAYS** use TypeScript with strict typing
- **ALWAYS** validate data with Zod
- **MANDATORY** to follow ESLint/Prettier standards
- **PROHIBITED** to use fallbacks for our own data

## 🛠️ Tech Stack

### Core

- **Vue 3** with Composition API
- **TypeScript** for type safety
- **Vite** as build tool
- **Pinia** for state management
- **Tailwind CSS v4** for styling

### Main Libraries

- **Reka UI** – Headless components
- **AG Grid Community** – Data tables
- **VeeValidate + Zod** – Form validation
- **Axios** – HTTP client
- **Vue Router** – Routing

## 📁 Project Structure

```
src/
├── components/          # Reusable components
│   ├── ui/             # Base components
│   ├── job/            # Job components
│   ├── timesheet/      # Timesheet components
│   └── kanban/         # Kanban components
├── composables/        # Shared logic
├── stores/             # Pinia stores
├── services/           # API layer
├── types/              # TypeScript types
├── views/              # Pages
└── api/generated/      # Auto-generated schemas
```

## 🔄 Development Flow

1. **Requirements Analysis** – Determine if it’s UI or database data
2. **Coordination** – Confirm with backend when needed
3. **Implementation** – Follow established standards
4. **Validation** – Testing and type checking
5. **Documentation** – Update relevant documentation

## 📖 How to Use These Rules

### For Developers

1. Read the critical architectural rules first
2. Consult specific rules as needed
3. Use cross-references to navigate related rules
4. Always coordinate with backend when in doubt

### For Kilo AI

- These rules are loaded automatically
- Follow all mandatory guidelines
- Use cross-references for additional context
- Coordinate with backend as specified

## 🔗 Cross-References

Rules include cross-references for easy navigation:

```markdown
## Related References

- See: [01-architectural-separation.md](./01-architectural-separation.md)
- See: [05-api-integration.md](./05-api-integration.md)
- See: [14-good-practices.md](./14-good-practices.md)
```

## 📝 Rule Maintenance

### When to Update

- Project architecture changes
- New libraries or tools
- Lessons learned from recurring issues
- Tech stack updates

### How to Update

1. Edit the specific rule file
2. Update cross-references if needed
3. Review consistency with other rules
4. Test with Kilo AI
5. Document changes

## 🎯 Rule Objectives

### Consistency

- Uniform standards throughout the project
- Consistent architectural decisions
- Maintained code quality

### Efficiency

- Reduce development time
- Avoid rework from incorrect decisions
- Facilitate maintenance and debugging

### Quality

- More readable and maintainable code
- Fewer bugs and integration issues
- Better performance and security

## 📞 Support

For questions about the rules or suggestions for improvement:

1. Check the project documentation
2. Review related rules
3. Coordinate with the backend team when needed
4. Document lessons learned for future updates

---

**Version:** 1.0  
**Last Update:** August 2025
**Compatible with:** Kilo Code AI, Vue 3, TypeScript 5+
