import { api } from '../api/client'
import { debugLog } from '../utils/debug'
import { z } from 'zod'
import { schemas } from '../api/generated/api'

type CompanySummary = z.infer<typeof schemas.CompanyNameOnly>
type CompanySearchResult = z.infer<typeof schemas.CompanySearchResult>
export type Company = CompanySummary | CompanySearchResult
export type CreateCompanyData = z.infer<typeof schemas.CompanyCreateRequest>
import type { CreateCompanyResponse } from '@/constants/company-wrapper'

export class CompanyService {
  private static instance: CompanyService

  static getInstance(): CompanyService {
    if (!CompanyService.instance) {
      CompanyService.instance = new CompanyService()
    }
    return CompanyService.instance
  }

  async createCompany(data: CreateCompanyData): Promise<CreateCompanyResponse> {
    try {
      const response = await api.companies_create_create(data)
      return {
        success: true,
        company: response?.company,
      }
    } catch (error: unknown) {
      debugLog('Error creating company:', error)
      return {
        success: false,
        error: 'Failed to create company',
      }
    }
  }

  async getAllCompanies(): Promise<CompanySummary[]> {
    try {
      const response = await api.companies_all_list()
      return Array.isArray(response) ? response : []
    } catch (error) {
      debugLog('Error fetching companies:', error)
      throw new Error('Failed to load companies')
    }
  }

  searchCompanies(companyList: Company[], searchTerm: string): Company[] {
    if (!searchTerm.trim()) {
      return companyList
    }

    const term = searchTerm.toLowerCase()
    return companyList.filter((company) => {
      const nameMatch = company.name.toLowerCase().includes(term)
      const emailMatch =
        'email' in company && typeof company.email === 'string'
          ? company.email.toLowerCase().includes(term)
          : false
      return nameMatch || emailMatch
    })
  }
}

export const companyService = CompanyService.getInstance()
