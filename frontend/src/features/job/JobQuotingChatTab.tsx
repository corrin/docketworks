import { ChatKit, useChatKit } from '@openai/chatkit-react'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { toast } from 'sonner'

import {
  apiErrorMessage,
  jobQuoteChatConfigRetrieveOptions,
  quotingChatFetch,
  quotingChatUrl,
} from '@/api'
import { QueryState } from '@/features/shared/QueryState'

export function JobQuotingChatTab({ jobId }: { jobId: string }) {
  const config = useQuery(jobQuoteChatConfigRetrieveOptions({ path: { job_id: jobId } }))
  return (
    <div className="min-w-0 p-6" data-automation-id="JobQuotingChatTab-root">
      <QueryState
        isPending={config.isPending}
        isError={config.isError}
        loadingLabel="Loading quoting chat…"
        errorLabel={apiErrorMessage(config.error, 'Could not load quoting chat.')}
        onRetry={() => void config.refetch()}
      >
        {config.data &&
          (config.data.domain_key === null ? (
            <p className="text-sm text-gray-600">
              Set the ChatKit domain key in Integrations settings to enable quoting chat.
            </p>
          ) : (
            <QuotingChat
              key={jobId}
              jobId={jobId}
              domainKey={config.data.domain_key}
              csrfToken={config.data.csrf_token}
            />
          ))}
      </QueryState>
    </div>
  )
}

function QuotingChat({
  jobId,
  domainKey,
  csrfToken,
}: {
  jobId: string
  domainKey: string
  csrfToken: string
}) {
  const fetch = useMemo(() => quotingChatFetch(jobId, csrfToken), [jobId, csrfToken])
  const { control } = useChatKit({
    api: { url: quotingChatUrl(jobId), domainKey, fetch },
    frameTitle: 'Quoting assistant',
    theme: { colorScheme: 'light', typography: { fontFamily: 'Inter, sans-serif', baseSize: 14 } },
    header: { title: { text: 'Quoting assistant' } },
    composer: { placeholder: 'Ask about materials, supplier prices or this job…' },
    startScreen: { greeting: 'What would you like to quote for this job?' },
    threadItemActions: { feedback: false },
    disclaimer: {
      text: 'Check prices and assumptions. Chat drafts do not change the job’s estimate.',
    },
    onError: ({ error }) => toast.error(apiErrorMessage(error, 'Quoting chat failed.')),
  })
  return <ChatKit control={control} className="block h-[calc(100dvh-15rem)] min-h-[480px] w-full" />
}
