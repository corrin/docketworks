import { createFileRoute } from '@tanstack/react-router'

import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage'

// No session guard either way: an anonymous visitor is the normal case, and a
// logged-in one requesting a reset email harms nothing.
export const Route = createFileRoute('/forgot-password')({
  component: ForgotPasswordPage,
})
