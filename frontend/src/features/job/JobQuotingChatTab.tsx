import { ChatKit, useChatKit } from '@openai/chatkit-react'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { Link } from '@tanstack/react-router'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobQuoteChatConfigRetrieveOptions,
  quotingChatFetch,
  quotingChatUrl,
  type QuotingChatModelOut,
} from '@/api'
import { QueryState } from '@/features/shared/QueryState'

export function JobQuotingChatTab({ jobId }: { jobId: string }) {
  const { t } = useTranslation('job')
  const config = useQuery(jobQuoteChatConfigRetrieveOptions({ path: { job_id: jobId } }))
  return (
    <div className="min-w-0 p-6" data-automation-id="JobQuotingChatTab-root">
      <QueryState
        isPending={config.isPending}
        isError={config.isError}
        loadingLabel={t('quotingChat.loading')}
        errorLabel={apiErrorMessage(config.error, t('quotingChat.loadFailed'))}
        onRetry={() => void config.refetch()}
      >
        {config.data &&
          (config.data.configuration_error !== null ? (
            <p className="text-sm text-gray-600">
              {config.data.configuration_error}{' '}
              {config.data.can_configure ? (
                <Link className="underline" to="/admin/integrations">
                  {t('quotingChat.configureIntegrations')}
                </Link>
              ) : (
                t('quotingChat.askAdministrator')
              )}
            </p>
          ) : config.data.domain_key !== null ? (
            <QuotingChat
              key={jobId}
              jobId={jobId}
              domainKey={config.data.domain_key}
              csrfToken={config.data.csrf_token}
              models={config.data.models}
            />
          ) : null)}
      </QueryState>
    </div>
  )
}

function QuotingChat({
  jobId,
  domainKey,
  csrfToken,
  models,
}: {
  jobId: string
  domainKey: string
  csrfToken: string
  models: QuotingChatModelOut[]
}) {
  const { t } = useTranslation('job')
  const fetch = useMemo(() => quotingChatFetch(jobId, csrfToken), [jobId, csrfToken])
  const { control } = useChatKit({
    api: { url: quotingChatUrl(jobId), domainKey, fetch },
    frameTitle: t('quotingChat.assistantTitle'),
    theme: { colorScheme: 'light', typography: { fontFamily: 'Inter, sans-serif', baseSize: 14 } },
    header: { title: { text: t('quotingChat.assistantTitle') } },
    composer: { placeholder: t('quotingChat.composerPlaceholder'), models },
    startScreen: { greeting: t('quotingChat.greeting') },
    threadItemActions: { feedback: false },
    disclaimer: {
      text: t('quotingChat.disclaimer'),
    },
    onError: ({ error }) => toast.error(apiErrorMessage(error, t('quotingChat.failed'))),
  })
  return <ChatKit control={control} className="block h-[calc(100dvh-15rem)] min-h-[480px] w-full" />
}
