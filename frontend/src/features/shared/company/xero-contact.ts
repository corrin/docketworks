import type { CompanySearchResult } from '@/api'

/**
 * A company can be invoiced (and so can carry jobs) only when it is linked to
 * a Xero contact. Job creation gates on this, not on mere selection.
 */
export function hasXeroContact(
  company: CompanySearchResult | null,
): company is CompanySearchResult {
  return company !== null && company.xero_contact_id !== ''
}
