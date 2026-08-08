import type { CompanyCreateResponse, CompanySearchResult } from '@/api'

/**
 * The create endpoint is Xero-first: the backend refuses to keep a local
 * company whose provider push failed, so a 201 without a xero_contact_id is
 * a backend contract violation, not a state the UI may accept quietly — the
 * job form downstream requires the Xero link.
 */
export function requireXeroLinkedCompany(response: CompanyCreateResponse): CompanySearchResult {
  if (!response.company.xero_contact_id) {
    throw new Error('Company was created but does not have a Xero ID')
  }
  return response.company
}
