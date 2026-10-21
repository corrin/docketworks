import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  assignPhoneCallNumberMutation,
  crmPhoneCallsListQueryKey,
  type CompanySearchResult,
  type PhoneCallRecordOut,
} from '@/api'
import { Button } from '@/components/ui/button'
import { INPUT_CLASS } from '@/components/ui/field'
import { CompanyLookup, PersonSelector, type SelectedPerson } from '@/features/shared/company'
import { orNull } from '@/features/shared/nullableText'
import { formatDateTime } from '@/lib/format'

interface AssignCallNumberPanelProps {
  call: PhoneCallRecordOut
  onClose: () => void
}

const ID = 'PhoneCallsPage'

/**
 * Claim an unmatched call's number for a company, and optionally for one
 * person at that company.
 *
 * The company-then-person pair is the one the people directory already uses.
 * v1's separate PhoneNumberManager card is not ported: contact methods have
 * one home in v2 (the person and company detail pages), and this panel covers
 * the only flow that starts from a call.
 */
export function AssignCallNumberPanel({ call, onClose }: AssignCallNumberPanelProps) {
  const { t } = useTranslation('crm')
  const queryClient = useQueryClient()
  const [company, setCompany] = useState<CompanySearchResult | null>(null)
  const [person, setPerson] = useState<SelectedPerson | null>(null)
  const [label, setLabel] = useState('')
  const [isPrimary, setIsPrimary] = useState(false)

  const assign = useMutation({
    ...assignPhoneCallNumberMutation(),
    onSuccess: () => {
      // Assigning a number rematches every OTHER call on it, so the refetched
      // list is the only accurate row set — the mutation's single call is not.
      void queryClient.invalidateQueries({ queryKey: crmPhoneCallsListQueryKey() })
      toast.success(t('assignPanel.assigned'))
      onClose()
    },
    onError: (error) => toast.error(apiErrorMessage(error, t('assignPanel.assignFailed'))),
  })

  return (
    <div
      data-automation-id={`${ID}-assign-panel`}
      className="mt-6 rounded-lg border border-gray-200 bg-white p-4 shadow-sm"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900">{t('assignPanel.title')}</h2>
          <p className="text-sm text-gray-500">
            {t('assignPanel.callFrom', {
              number: call.external_number,
              when: formatDateTime(call.call_datetime),
            })}
          </p>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          data-automation-id={`${ID}-assign-cancel`}
          onClick={onClose}
        >
          {t('assignPanel.cancel')}
        </Button>
      </div>

      <div className="mt-4 grid max-w-2xl gap-4">
        <CompanyLookup
          id="assign-call-number-company"
          label={t('assignPanel.company')}
          required
          selectedCompany={company}
          onSelectCompany={(next) => {
            setCompany(next)
            // The person belongs to the company that was chosen before; keeping
            // one across a change would claim the number for a stranger.
            setPerson(null)
          }}
        />
        {company !== null && (
          <PersonSelector
            id="assign-call-number-person"
            label={t('assignPanel.person')}
            optional
            companyId={company.id}
            companyName={company.name}
            selectedPerson={person}
            autoSelectPrimary={false}
            onSelectPerson={(next) =>
              setPerson(
                next === null ? null : { person_id: next.person_id, person_name: next.person_name },
              )
            }
          />
        )}
        <label
          htmlFor="assign-call-number-label"
          className="flex flex-col gap-1 text-sm font-medium text-gray-700"
        >
          {t('assignPanel.label')}{' '}
          <span className="text-xs font-normal text-gray-500">{t('assignPanel.optional')}</span>
          <input
            id="assign-call-number-label"
            type="text"
            className={INPUT_CLASS}
            placeholder={t('assignPanel.labelPlaceholder')}
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            data-automation-id={`${ID}-assign-label`}
          />
        </label>
        <label className="flex items-center gap-2 text-sm text-gray-700">
          <input
            type="checkbox"
            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
            checked={isPrimary}
            onChange={(event) => setIsPrimary(event.target.checked)}
            data-automation-id={`${ID}-assign-primary`}
          />
          {t('assignPanel.primary')}
        </label>
        <div>
          <Button
            type="button"
            data-automation-id={`${ID}-assign-submit`}
            disabled={company === null || assign.isPending}
            onClick={() => {
              if (company === null) {
                throw new Error(
                  'Assign was pressed with no company, but it is disabled until one is',
                )
              }
              assign.mutate({
                path: { call_id: call.id },
                body: {
                  company: company.id,
                  person: person === null ? null : person.person_id,
                  is_primary: isPrimary,
                  label: orNull(label),
                },
              })
            }}
          >
            {assign.isPending ? t('assignPanel.assigning') : t('assignPanel.assign')}
          </Button>
        </div>
      </div>
    </div>
  )
}
