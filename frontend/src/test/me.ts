import { http, HttpResponse } from 'msw'

import type { UserProfile } from '@/api'

import { server } from './msw'

/**
 * Answer GET /api/accounts/me/ with an office-staff, non-superuser profile,
 * overridden per test. The one place a test says who is looking: every
 * office-only surface in the app gates on this response, so each test file
 * inventing its own profile is how two of them would disagree about what
 * `is_office_staff: false` renders.
 */
export function mockUser(overrides: Partial<UserProfile> = {}): void {
  server.use(
    http.get('*/api/accounts/me/', () =>
      HttpResponse.json({
        id: '11111111-1111-1111-1111-111111111111',
        office_email: 'someone@example.com',
        payroll_email: null,
        first_name: 'Some',
        last_name: 'One',
        preferred_name: null,
        fullName: 'Some One',
        is_office_staff: true,
        is_superuser: false,
        password_needs_reset: false,
        ...overrides,
      }),
    ),
  )
}
