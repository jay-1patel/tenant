import { useState, type ReactNode } from 'react'
import { Check, ClipboardCheck, Send, X } from 'lucide-react'
import {
  tenantApprovalsApi,
  type TenantChangeRequest,
  type TenantChangeStatus,
} from '@/lib/tenant-approvals'
import { useAsync, useAction } from '@/lib/hooks'
import { formatDate, isTruthyFlag } from '@/lib/format'
import { tenantsApi } from '@/lib/tenants'
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

/** Green highlight for values the admin changed against the live profile. */
function Edited({ changed, children }: { changed: boolean; children: ReactNode }) {
  if (!changed) return <>{children}</>
  return (
    <span
      className="rounded bg-emerald-500/10 px-1.5 py-0.5 text-emerald-300 ring-1 ring-inset ring-emerald-500/30"
      title="Changed by the admin"
    >
      {children}
    </span>
  )
}

/**
 * Everything the admin entered, field by field — the review counterpart of the
 * wizard's own steps. Empty fields read as an em dash so a gap is visible
 * rather than silently missing. For profile publishes the live profile is the
 * baseline: fields the admin actually changed are highlighted in green.
 */
function SnapshotDetails({
  request,
  baseline,
}: {
  request: TenantChangeRequest
  baseline?: Record<string, any>
}) {
  const snapshot = (request.payload.snapshot ?? {}) as Record<string, any>
  const brand = snapshot.brand ?? {}
  const hours = snapshot.business_hours ?? {}
  const notes = snapshot.notifications ?? {}
  const rails = snapshot.guardrails ?? {}
  const prompt = snapshot.prompt ?? {}
  const menu = (snapshot.menu ?? {}) as { header?: string; body?: string }
  const channels: { type?: string; to?: string; label?: string }[] = notes.channels ?? []

  const openDays: number[] = Array.isArray(hours.open_days) ? hours.open_days : []

  const at = (source: unknown, path: string): unknown =>
    path
      .split('.')
      .reduce<unknown>(
        (acc, key) =>
          acc && typeof acc === 'object' ? (acc as Record<string, unknown>)[key] : undefined,
        source,
      )

  /** True when a submitted value exists and differs from the live profile. */
  const edited = (path: string): boolean => {
    if (!baseline) return false
    const submitted = at(snapshot, path)
    if (submitted === undefined || submitted === null) return false
    return JSON.stringify(submitted) !== JSON.stringify(at(baseline, path) ?? null)
  }

  const editedAny = (paths: string[]): boolean => paths.some(edited)

  return (
    <div className="space-y-4">
      <DetailSection
        title="Company"
        rows={[
          [
            'Display name',
            <Edited key="dn" changed={edited('display_name')}>
              {valueOr(snapshot.display_name, request.tenant_display_name)}
            </Edited>,
          ],
          [
            'Business field',
            <Edited key="v" changed={edited('vertical')}>
              {valueOr(snapshot.vertical, request.tenant_vertical)}
            </Edited>,
          ],
          [
            'Company',
            <Edited key="cn" changed={edited('brand.name')}>
              {valueOr(brand.name)}
            </Edited>,
          ],
          [
            'Website',
            <Edited key="w" changed={edited('brand.website')}>
              {valueOr(brand.website)}
            </Edited>,
          ],
        ]}
      />
      <DetailSection
        title="WhatsApp and working hours"
        rows={[
          ['WhatsApp phone id', valueOr(request.tenant_waba_phone_id, 'not bound')],
          [
            'Timezone',
            <Edited key="tz" changed={edited('business_hours.timezone')}>
              {valueOr(hours.timezone)}
            </Edited>,
          ],
          [
            'Working hours',
            <Edited
              key="hrs"
              changed={editedAny([
                'business_hours.always_open',
                'business_hours.open',
                'business_hours.close',
                'business_hours.open_days',
              ])}
            >
              <span>
                {hours.always_open
                  ? 'Always open'
                  : `${valueOr(hours.open)}–${valueOr(hours.close)} · ${
                      openDays.length
                        ? openDays.map((d) => DAY_LABELS[d] ?? String(d)).join(', ')
                        : 'no days set'
                    }`}
              </span>
            </Edited>,
          ],
          [
            'Out-of-hours message',
            <Edited key="ooh" changed={edited('business_hours.out_of_hours_message')}>
              {valueOr(hours.out_of_hours_message)}
            </Edited>,
          ],
        ]}
      />
      <DetailSection
        title="Brand and voice"
        rows={[
          [
            'Bot name',
            <Edited key="bn" changed={edited('brand.bot_name')}>
              {valueOr(brand.bot_name)}
            </Edited>,
          ],
          [
            'Tagline',
            <Edited key="tg" changed={edited('brand.tagline')}>
              {valueOr(brand.tagline)}
            </Edited>,
          ],
          [
            'Tone',
            <Edited key="to" changed={edited('prompt.tone')}>
              {valueOr(prompt.tone)}
            </Edited>,
          ],
          [
            'Support email',
            <Edited key="se" changed={edited('brand.support_email')}>
              {valueOr(brand.support_email)}
            </Edited>,
          ],
          [
            'Support phone',
            <Edited key="sp" changed={edited('brand.support_phone')}>
              {valueOr(brand.support_phone)}
            </Edited>,
          ],
          [
            'Closing signature',
            <Edited key="sig" changed={edited('brand.signature')}>
              {valueOr(brand.signature)}
            </Edited>,
          ],
          [
            'Menu greeting',
            <Edited key="mg" changed={edited('menu.body')}>
              {valueOr(menu.body)}
            </Edited>,
          ],
        ]}
      />
      <DetailSection
        title="Notifications"
        rows={[
          [
            'Sales email',
            <Edited key="sle" changed={edited('notifications.sales_email')}>
              {valueOr(notes.sales_email)}
            </Edited>,
          ],
          [
            'Support email',
            <Edited key="nse" changed={edited('notifications.support_email')}>
              {valueOr(notes.support_email)}
            </Edited>,
          ],
          [
            'Brochure URL',
            <Edited key="bu" changed={edited('notifications.brochure_url')}>
              {valueOr(notes.brochure_url)}
            </Edited>,
          ],
          [
            'Extra channels',
            <Edited key="ch" changed={edited('notifications.channels')}>
              {channels.length ? (
                <ul className="space-y-0.5">
                  {channels.map((c, i) => (
                    <li key={i}>
                      {valueOr(c.type)} → {valueOr(c.to)}
                      {c.label ? ` (${c.label})` : ''}
                    </li>
                  ))}
                </ul>
              ) : (
                '—'
              )}
            </Edited>,
          ],
        ]}
      />
      <DetailSection
        title="Guardrails"
        rows={[
          [
            'Never state',
            <Edited key="ns" changed={edited('guardrails.never_state')}>
              <span>
                {(rails.never_state ?? []).length
                  ? (rails.never_state as string[]).map((line, i) => (
                      <span key={i} className="block">
                        • {line}
                      </span>
                    ))
                  : '—'}
              </span>
            </Edited>,
          ],
          [
            'Forbidden terms',
            <Edited key="ft" changed={edited('guardrails.forbidden_terms')}>
              {valueOr(rails.forbidden_terms)}
            </Edited>,
          ],
          [
            'Handoff keywords',
            <Edited key="hk" changed={edited('guardrails.handoff_keywords')}>
              {valueOr(rails.handoff_keywords)}
            </Edited>,
          ],
          [
            'Escalate on',
            <Edited key="ek" changed={edited('guardrails.escalate_keywords')}>
              {valueOr(rails.escalate_keywords)}
            </Edited>,
          ],
          [
            'Escalation message',
            <Edited key="em" changed={edited('guardrails.escalation_message')}>
              {valueOr(rails.escalation_message)}
            </Edited>,
          ],
        ]}
      />
    </div>
  )
}

function RequestPayload({ request }: { request: TenantChangeRequest }) {
  const [open, setOpen] = useState(false)
  // For profile publishes the tenant's live profile is the diff baseline:
  // fields whose submitted value differs from it are the admin's edits and
  // show in green. Registrations have no prior profile to compare against.
  const baselineState = useAsync(
    (signal) =>
      request.request_type === 'publish_profile'
        ? tenantsApi.detail(request.tenant_id, signal)
        : Promise.resolve(null),
    [request.id, request.request_type, request.tenant_id],
  )
  const baseline = baselineState.data?.effective as unknown as
    | Record<string, any>
    | undefined

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
      <SnapshotDetails request={request} baseline={baseline} />
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
