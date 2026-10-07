import { useState } from 'react'
import { Check, X } from 'lucide-react'
import { apiOnboarding, type ApiOnboardingRequest, type ApiOnboardingStatus } from '@/lib/api-onboarding'
import { useAsync, useAction } from '@/lib/hooks'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const LABELS = { payment_api: 'Payment Gateway API', order_api: 'Order & Shipping API' } as const
const TONES: Record<ApiOnboardingStatus, 'warning' | 'success' | 'danger'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
}

export function ApiOnboardingReview() {
  const [filter, setFilter] = useState<ApiOnboardingStatus | 'all'>('pending')
  const state = useAsync((signal) => apiOnboarding.all(filter === 'all' ? undefined : filter, signal), [filter])
  const action = useAction()
  const toast = useToast()
  const [notes, setNotes] = useState<Record<number, string>>({})

  const decide = async (request: ApiOnboardingRequest, decision: 'approved' | 'rejected') => {
    const result = await action.run(() => apiOnboarding.decide(request.id, decision, notes[request.id] ?? ''))
    if (result) {
      toast.push(`${LABELS[request.api_type]} request ${decision}`)
      setNotes((current) => ({ ...current, [request.id]: '' }))
      state.reload()
    }
  }

  return (
    <div>
      <PageHeader
        title="API access requests"
        description="Review tenant requests for external Payment API and Order API access. Approval grants eligibility only; it does not configure credentials or enable live traffic."
        meta={<Badge tone="accent">Superadmin review</Badge>}
      />

      <Alert tone="info" title="Approval is not live activation" className="mb-4">
        Approved requests still require secure credential provisioning before any API connection can be enabled. Never ask tenants to send API secrets through this queue.
      </Alert>

      <div className="mb-4 max-w-xs">
        <Select label="Request status" value={filter} onChange={(event) => setFilter(event.target.value as ApiOnboardingStatus | 'all')}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="all">All requests</option>
        </Select>
      </div>

      {action.error && <Alert tone="danger" title="Could not update request" className="mb-4">{action.error}</Alert>}
      {state.loading && <LoadingBlock label="Loading API requests…" />}
      {state.error && <Alert tone="danger" title="Could not load API requests">{state.error}</Alert>}
      {state.data?.length === 0 && !state.loading && (
        <Card><EmptyState title="No requests" description="There are no API access requests in this status." /></Card>
      )}
      {state.data && state.data.length > 0 && (
        <div className="space-y-3">
          {state.data.map((request: ApiOnboardingRequest) => (
            <Card key={request.id}>
              <CardHeader
                title={`${LABELS[request.api_type as keyof typeof LABELS]} · ${request.tenant_id}`}
                description={`Submitted by ${request.requester_username} on ${formatDate(request.created_at)}${request.provider ? ` · ${request.provider}` : ''} · ${request.environment}`}
                actions={<Badge tone={TONES[request.status as ApiOnboardingStatus]}>{request.status}</Badge>}
              />
              <CardBody className="space-y-4">
                <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{request.purpose}</p>
                {request.status === 'pending' ? (
                  <>
                    <Textarea
                      label="Decision note (optional)"
                      rows={2}
                      maxLength={2000}
                      value={notes[request.id] ?? ''}
                      onChange={(event) => setNotes((current) => ({ ...current, [request.id]: event.target.value }))}
                      hint="Visible to the tenant admin. Do not include credentials or secrets."
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button variant="primary" loading={action.busy} icon={<Check className="h-4 w-4" />} onClick={() => decide(request, 'approved')}>
                        Approve eligibility
                      </Button>
                      <Button variant="danger" loading={action.busy} icon={<X className="h-4 w-4" />} onClick={() => decide(request, 'rejected')}>
                        Reject request
                      </Button>
                    </div>
                  </>
                ) : (
                  <div className="rounded-lg bg-surface-panel p-3 text-xs text-slate-400">
                    Reviewed by {request.reviewer_username || 'superadmin'}{request.decided_at ? ` on ${formatDate(request.decided_at)}` : ''}
                    {request.decision_note && <p className="mt-1 whitespace-pre-wrap text-slate-300">{request.decision_note}</p>}
                    {request.status === 'approved' && <p className="mt-2 text-emerald-700">{request.eligible ? 'Eligibility granted.' : 'Eligibility was not recorded; contact engineering.'} Secure setup is still required before live API use.</p>}
                  </div>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
