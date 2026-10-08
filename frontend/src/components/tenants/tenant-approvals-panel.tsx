import { useState, type ReactNode } from 'react'
import { Check, ClipboardCheck, Send, X } from 'lucide-react'
import {
  tenantApprovalsApi,
  type TenantChangeRequest,
  type TenantChangeStatus,
} from '@/lib/tenant-approvals'
import { useAsync, useAction } from '@/lib/hooks'
import { formatDate, isTruthyFlag } from '@/lib/format'
import { FEATURE_LABELS } from '@/lib/verticals'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const TONES: Record<TenantChangeStatus, 'warning' | 'success' | 'danger'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
}

const TYPE_LABELS = {
  create_tenant: 'Register a tenant',
  publish_profile: 'Publish profile',
} as const

const DAY_LABELS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

function valueOr(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined) return fallback
  if (typeof value === 'string') return value.trim() ? value : fallback
  if (Array.isArray(value)) return value.length ? value.join(', ') : fallback
  return String(value)
}

function DetailSection({ title, rows }: { title: string; rows: [string, ReactNode][] }) {
  if (rows.length === 0) return null
  return (
    <div>
      <p className="field-label mb-1.5">{title}</p>
      <div className="divide-y divide-surface-line rounded-lg ring-1 ring-inset ring-surface-line">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-start gap-4 px-4 py-2.5">
            <span className="w-40 shrink-0 text-xs text-slate-500">{label}</span>
            <span className="min-w-0 flex-1 whitespace-pre-wrap text-xs text-slate-200">{value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/**
 * Everything the admin entered, field by field — the review counterpart of the
 * wizard's own steps. Anything the profile carries is shown; empty fields read
 * as an em dash so a gap is visible rather than silently missing.
 */
function SnapshotDetails({ request }: { request: TenantChangeRequest }) {
  const snapshot = (request.payload.snapshot ?? {}) as Record<string, any>
  const brand = snapshot.brand ?? {}
  const hours = snapshot.business_hours ?? {}
  const notes = snapshot.notifications ?? {}
  const rails = snapshot.guardrails ?? {}
  const vocab = snapshot.vocabulary ?? {}
  const prompt = snapshot.prompt ?? {}
  const menu = (snapshot.menu ?? {}) as { header?: string; body?: string }
  const channels: { type?: string; to?: string; label?: string }[] = notes.channels ?? []

  const features = snapshot.features ?? {}
  const enabledFeatures = Object.keys(features).filter((f) => features[f])
  const featureLabels = FEATURE_LABELS as Record<string, { label: string }>

  const openDays: number[] = Array.isArray(hours.open_days) ? hours.open_days : []

  return (
    <div className="space-y-4">
      <DetailSection
        title="Company"
        rows={[
          ['Display name', valueOr(snapshot.display_name, request.tenant_display_name)],
          ['Business field', valueOr(snapshot.vertical, request.tenant_vertical)],
          ['Company', valueOr(brand.name)],
          ['Website', valueOr(brand.website)],
        ]}
      />
      <DetailSection
        title="WhatsApp and working hours"
        rows={[
          ['WhatsApp phone id', valueOr(request.tenant_waba_phone_id, 'not bound')],
          ['Timezone', valueOr(hours.timezone)],
          [
            'Working hours',
            <span key="hours">
              {hours.always_open
                ? 'Always open'
                : `${valueOr(hours.open)}–${valueOr(hours.close)} · ${
                    openDays.length ? openDays.map((d) => DAY_LABELS[d] ?? String(d)).join(', ') : 'no days set'
                  }`}
            </span>,
          ],
          ['Out-of-hours message', valueOr(hours.out_of_hours_message)],
        ]}
      />
      <DetailSection
        title="Brand and voice"
        rows={[
          ['Bot name', valueOr(brand.bot_name)],
          ['Tagline', valueOr(brand.tagline)],
          ['Tone', valueOr(prompt.tone)],
          ['Support email', valueOr(brand.support_email)],
          ['Support phone', valueOr(brand.support_phone)],
          ['Closing signature', valueOr(brand.signature)],
          ['Menu greeting', valueOr(menu.body)],
          [
            'Vocabulary',
            valueOr(
              [vocab.item_noun, vocab.lead_noun].filter(Boolean).join(' · '),
            ),
          ],
        ]}
      />
      <DetailSection
        title="Capabilities"
        rows={[
          [
            'Enabled features',
            <span key="features" className="flex flex-wrap gap-1.5">
              {enabledFeatures.length ? (
                enabledFeatures.map((f) => (
                  <span key={f} className="rounded bg-surface-panel px-1.5 py-0.5 text-xs text-slate-300">
                    {featureLabels[f]?.label ?? f.replace(/_/g, ' ')}
                  </span>
                ))
              ) : (
                'none enabled'
              )}
            </span>,
          ],
          ['Domain keywords', valueOr(prompt.keywords)],
        ]}
      />
      <DetailSection
        title="Notifications"
        rows={[
          ['Sales email', valueOr(notes.sales_email)],
          ['Support email', valueOr(notes.support_email)],
          ['Brochure URL', valueOr(notes.brochure_url)],
          [
            'Extra channels',
            channels.length ? (
              <ul key="channels" className="space-y-0.5">
                {channels.map((c, i) => (
                  <li key={i}>
                    {valueOr(c.type)} → {valueOr(c.to)}
                    {c.label ? ` (${c.label})` : ''}
                  </li>
                ))}
              </ul>
            ) : (
              '—'
            ),
          ],
        ]}
      />
      <DetailSection
        title="Guardrails"
        rows={[
          [
            'Never state',
            <span key="never">
              {(rails.never_state ?? []).length
                ? (rails.never_state as string[]).map((line, i) => (
                    <span key={i} className="block">
                      • {line}
                    </span>
                  ))
                : '—'}
            </span>,
          ],
          ['Forbidden terms', valueOr(rails.forbidden_terms)],
          ['Handoff keywords', valueOr(rails.handoff_keywords)],
          ['Escalate on', valueOr(rails.escalate_keywords)],
          ['Escalation message', valueOr(rails.escalation_message)],
        ]}
      />
    </div>
  )
}

function RequestPayload({ request }: { request: TenantChangeRequest }) {
  const [open, setOpen] = useState(false)

  return (
    <div className="space-y-4">
      {request.request_type === 'create_tenant' && (
        <DetailSection
          title="Tenant registry"
          rows={[
            ['Tenant id', request.tenant_id],
            ['Display name', valueOr(request.payload.tenant?.display_name, request.tenant_display_name)],
            ['Business field', valueOr(request.payload.tenant?.vertical, request.tenant_vertical)],
            ['WhatsApp phone id', valueOr(request.tenant_waba_phone_id, 'not bound')],
            ['Status', valueOr(request.payload.tenant?.status, 'active')],
          ]}
        />
      )}
      <SnapshotDetails request={request} />
      <div>
        <Button size="sm" variant="ghost" onClick={() => setOpen((v) => !v)}>
          {open ? 'Hide' : 'Inspect'} raw submitted data
        </Button>
        {open && (
          <pre className="mt-2 max-h-72 overflow-auto scroll-thin rounded-lg bg-surface p-4 font-mono text-xs leading-relaxed text-slate-400">
            {JSON.stringify(request.payload, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

function RequestCard({
  request,
  onDecide,
  busy,
  note,
  onNoteChange,
}: {
  request: TenantChangeRequest
  onDecide: (request: TenantChangeRequest, decision: 'approved' | 'rejected') => void
  busy: boolean
  note: string
  onNoteChange: (note: string) => void
}) {
  return (
    <Card>
      <CardHeader
        title={`${TYPE_LABELS[request.request_type]} · ${request.tenant_id}`}
        description={`Submitted by ${request.requester_username} on ${formatDate(request.created_at)}`}
        actions={<Badge tone={TONES[request.status]}>{request.status}</Badge>}
      />
      <CardBody className="space-y-4">
        <RequestPayload request={request} />
        {request.status === 'pending' ? (
          <>
            <Textarea
              label="Decision note (optional)"
              rows={2}
              maxLength={2000}
              value={note}
              onChange={(event) => onNoteChange(event.target.value)}
              hint="Visible to the requester."
            />
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" loading={busy} icon={<Check className="h-4 w-4" />} onClick={() => onDecide(request, 'approved')}>
                Approve and apply
              </Button>
              <Button variant="danger" loading={busy} icon={<X className="h-4 w-4" />} onClick={() => onDecide(request, 'rejected')}>
                Reject request
              </Button>
            </div>
          </>
        ) : (
          <div className="rounded-lg bg-surface-panel p-3 text-xs text-slate-400">
            Reviewed by {request.reviewer_username || 'super admin'}
            {request.decided_at ? ` on ${formatDate(request.decided_at)}` : ''}
            {request.decision_note && (
              <p className="mt-1 whitespace-pre-wrap text-slate-300">{request.decision_note}</p>
            )}
            {request.status === 'approved' && (
              <p className="mt-2 text-emerald-700">
                {isTruthyFlag(request.applied)
                  ? `Applied — live on version ${request.applied_version ?? '?'}.`
                  : 'Approved but not applied; contact engineering.'}
              </p>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  )
}

/** Super admin side: the queue of registrations and publishes awaiting approval. */
export function TenantChangeReview() {
  const [filter, setFilter] = useState<TenantChangeStatus | 'all'>('pending')
  const state = useAsync((signal) => tenantApprovalsApi.all(filter === 'all' ? undefined : filter, signal), [filter])
  const action = useAction()
  const toast = useToast()
  const [notes, setNotes] = useState<Record<number, string>>({})

  const decide = async (request: TenantChangeRequest, decision: 'approved' | 'rejected') => {
    const result = await action.run(() =>
      tenantApprovalsApi.decide(request.id, decision, notes[request.id] ?? ''),
    )
    if (result) {
      toast.push(result.message ?? `${TYPE_LABELS[request.request_type]} request ${decision}`)
      setNotes((current) => ({ ...current, [request.id]: '' }))
      state.reload()
    }
  }

  return (
    <div>
      <PageHeader
        title="Tenant change requests"
        description="Tenant registrations and profile publishes submitted by admins. Approval applies the change exactly as it was submitted; rejection leaves the live tenant untouched."
        meta={<Badge tone="accent">Superadmin review</Badge>}
      />

      <div className="mb-4 max-w-xs">
        <Select label="Request status" value={filter} onChange={(event) => setFilter(event.target.value as TenantChangeStatus | 'all')}>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="all">All requests</option>
        </Select>
      </div>

      {action.error && <Alert tone="danger" title="Could not update request" className="mb-4">{action.error}</Alert>}
      {state.loading && <LoadingBlock label="Loading tenant change requests…" />}
      {state.error && <Alert tone="danger" title="Could not load requests">{state.error}</Alert>}
      {state.data?.length === 0 && !state.loading && (
        <Card>
          <EmptyState
            icon={<ClipboardCheck className="h-8 w-8" />}
            title="No requests"
            description="There are no tenant change requests in this status. Admin submissions appear here for approval."
          />
        </Card>
      )}
      {state.data && state.data.length > 0 && (
        <div className="space-y-3">
          {state.data.map((request) => (
            <RequestCard
              key={request.id}
              request={request}
              onDecide={decide}
              busy={action.busy}
              note={notes[request.id] ?? ''}
              onNoteChange={(note) => setNotes((current) => ({ ...current, [request.id]: note }))}
            />
          ))}
        </div>
      )}
    </div>
  )
}

/** Admin side: the requests this admin submitted and where they stand. */
export function MyTenantChangeRequests() {
  const state = useAsync((signal) => tenantApprovalsApi.mine(signal), [])
  const [open, setOpen] = useState<number | null>(null)

  return (
    <div>
      <PageHeader
        title="My change requests"
        description="Tenant registrations and profile publishes you submitted. Nothing goes live until a super admin approves it."
        meta={<Badge tone="neutral">Pending super admin approval</Badge>}
      />

      {state.loading && <LoadingBlock label="Loading your requests…" />}
      {state.error && <Alert tone="danger" title="Could not load requests">{state.error}</Alert>}
      {state.data?.length === 0 && !state.loading && (
        <Card>
          <EmptyState
            icon={<Send className="h-8 w-8" />}
            title="No requests yet"
            description="Register a tenant or publish a profile and your submission will appear here while it waits for approval."
          />
        </Card>
      )}
      {state.data && state.data.length > 0 && (
        <div className="space-y-3">
          {state.data.map((request) => (
            <Card key={request.id}>
              <CardHeader
                title={`${TYPE_LABELS[request.request_type]} · ${request.tenant_id}`}
                description={`Submitted on ${formatDate(request.created_at)}`}
                actions={<Badge tone={TONES[request.status]}>{request.status}</Badge>}
              />
              <CardBody className="space-y-3">
                <p className="text-xs text-slate-300">{request.summary}</p>
                {request.status !== 'pending' && (
                  <div className="rounded-lg bg-surface-panel p-3 text-xs text-slate-400">
                    Reviewed by {request.reviewer_username || 'super admin'}
                    {request.decided_at ? ` on ${formatDate(request.decided_at)}` : ''}
                    {request.decision_note && (
                      <p className="mt-1 whitespace-pre-wrap text-slate-300">{request.decision_note}</p>
                    )}
                    {request.status === 'approved' && isTruthyFlag(request.applied) && (
                      <p className="mt-2 text-emerald-700">
                        Applied — live on version {request.applied_version ?? '?'}.
                      </p>
                    )}
                  </div>
                )}
                {request.status === 'pending' && (
                  <Button size="sm" variant="ghost" onClick={() => setOpen(open === request.id ? null : request.id)}>
                    {open === request.id ? 'Hide' : 'Inspect'} submitted data
                  </Button>
                )}
                {open === request.id && (
                  <pre className="max-h-72 overflow-auto scroll-thin rounded-lg bg-surface p-4 font-mono text-xs leading-relaxed text-slate-400">
                    {JSON.stringify(request.payload, null, 2)}
                  </pre>
                )}
              </CardBody>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
