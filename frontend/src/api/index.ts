/**
 * The app-facing API surface. Features import queryOptions/mutations from here,
 * never from src/api/generated (enforced by scripts/check-api-boundary.mjs).
 * Add re-exports as new domains come online.
 */

// Importing the client module configures it (baseURL, cookies, trim + ETag
// interceptors); re-exporting makes that dependency explicit and consumable.
export { client } from './client'

// Auth (accounts endpoints)
export {
  accountsLogoutCreateMutation,
  accountsMeRetrieveOptions,
  accountsMeRetrieveQueryKey,
  accountsTokenCreateMutation,
} from './generated/@tanstack/react-query.gen'
export type { CustomTokenObtainPairRequest, UserProfile } from './generated/types.gen'
