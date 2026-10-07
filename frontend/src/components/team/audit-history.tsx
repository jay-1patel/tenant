import { useState } from 'react'
import { Search, ChevronLeft, ChevronRight } from 'lucide-react'
import { auditApi, type AuditOutcome, type AuditFilters } from '@/lib/audit'
import { useAsync } from '@/lib/hooks'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

const PAGE_SIZE = 50
const LABELS: Record<string, string> = {
  login: 'Login',
  first_admin_created: 'Initial superadmin created',
  admin_created: 'Admin account created',
  admin_updated: 'Admin account updated',
  admin_deleted: 'Admin account deleted',
  admin_password_reset: 'Admin password reset',
  admin_password_reset_via_otp: 'Password reset by recovery',
  password_changed: 'Password changed',
  tenant_created: 'Tenant created',
  tenant_deleted: 'Tenant deleted',
  tenant_profile_draft_saved: 'Tenant profile draft saved',
  tenant_intent_draft_saved: 'Tenant page draft saved',
  tenant_profile_published: 'Tenant profile published',
  tenant_profile_rolled_back: 'Tenant profile rolled back',
  tenant_phone_id_bound: 'Tenant phone ID bound',
  tenant_webhook_secret_configured: 'Tenant webhook secret configured',
  tenant_token_created: 'Tenant token created',
  tenant_token_revoked: 'Tenant token revoked',
  api_access_request_submitted: 'API access request submitted',
  api_access_request_reviewed: 'API access request reviewed',
  config_draft_saved: 'Configuration draft saved',
  config_draft_built: 'Configuration draft generated',
  config_published: 'Configuration published',
}

function describeDetails(details: Record<string, unknown>) {
  const parts: string[] = []
  if (typeof details.role === 'string') parts.push(`Role: ${details.role}`)
  if (typeof details.role_before === 'string' && typeof details.role_after === 'string' && details.role_before !== details.role_after) {
    parts.push(`Role changed: ${details.role_before} → ${details.role_after}`)
  }
  if (typeof details.version === 'number') parts.push(`Version ${details.version}`)
  if (typeof details.decision === 'string') parts.push(`Decision: ${details.decision}`)
  if (typeof details.api_type === 'string') parts.push(`Type: ${details.api_type}`)
  if (typeof details.scope === 'string') parts.push(`Scope: ${details.scope}`)
  if (Array.isArray(details.changed_sections)) parts.push(`Sections: ${details.changed_sections.join(', ')}`)
  if (Array.isArray(details.changed_fields)) parts.push(`Fields: ${details.changed_fields.join(', ')}`)
  if (Array.isArray(details.permission_keys_changed) && details.permission_keys_changed.length) {
    parts.push(`Permissions changed: ${details.permission_keys_changed.join(', ')}`)
  }
  if (typeof details.configured === 'boolean') parts.push(details.configured ? 'Configured' : 'Not configured')
  if (typeof details.label === 'string' && details.label) parts.push(`Label: ${details.label}`)
  return parts.join(' · ')
}

export function AuditHistory() {
  const [filters, setFilters] = useState<AuditFilters>({ limit: PAGE_SIZE, offset: 0 })
  const [draft, setDraft] = useState({ search: '', actor: '', action: '', category: '', tenant_id: '', outcome: '' as AuditOutcome | '', start_date: '', end_date: '' })
  const state = useAsync((signal) => auditApi.list(filters, signal), [filters])

  const apply = () => {
    setFilters({
      ...draft,
      limit: PAGE_SIZE,
      offset: 0,
    })
  }
  const page = state.data
  const start = page && page.total ? page.offset + 1 : 0
  const end = page ? Math.min(page.offset + page.events.length, page.total) : 0

  return (
    <div>
      <PageHeader
        title="Audit history"
        description="Review admin and sub-admin logins and account or tenant setup changes. Records are retained for one year."
        meta={<Badge tone="accent">Superadmin only</Badge>}
      />

      <Card className="mb-4">
        <CardBody className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <Input label="Search" placeholder="Actor, target, action, or resource" value={draft.search} onChange={(event) => setDraft((value) => ({ ...value, search: event.target.value }))} />
            <Input label="Actor username" value={draft.actor} onChange={(event) => setDraft((value) => ({ ...value, actor: event.target.value }))} />
            <Select label="Action" value={draft.action} onChange={(event) => setDraft((value) => ({ ...value, action: event.target.value }))}>
              <option value="">All actions</option>
              {Object.entries(LABELS).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </Select>
            <Select label="Category" value={draft.category} onChange={(event) => setDraft((value) => ({ ...value, category: event.target.value }))}>
              <option value="">All categories</option>
              <option value="authentication">Authentication</option>
              <option value="accounts">Admin accounts</option>
              <option value="tenant_setup">Tenant setup</option>
              <option value="api_access">API access</option>
            </Select>
            <Input label="Tenant ID" value={draft.tenant_id} onChange={(event) => setDraft((value) => ({ ...value, tenant_id: event.target.value }))} />
            <Select label="Outcome" value={draft.outcome} onChange={(event) => setDraft((value) => ({ ...value, outcome: event.target.value as AuditOutcome | '' }))}>
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </Select>
            <div className="grid grid-cols-2 gap-3">
              <Input label="From" type="date" value={draft.start_date} onChange={(event) => setDraft((value) => ({ ...value, start_date: event.target.value }))} />
              <Input label="To" type="date" value={draft.end_date} onChange={(event) => setDraft((value) => ({ ...value, end_date: event.target.value }))} />
            </div>
          </div>
          <Button variant="primary" icon={<Search className="h-4 w-4" />} onClick={apply}>Apply filters</Button>
        </CardBody>
      </Card>

      {state.error && <Alert tone="danger" title="Could not load audit history">{state.error}</Alert>}
      {state.loading && <LoadingBlock label="Loading audit history…" />}
      {page?.events.length === 0 && !state.loading && <Card><EmptyState title="No activity found" description="Try changing the filters or date range." /></Card>}
      {page && page.events.length > 0 && (
        <>
          <div className="mb-3 flex items-center justify-between text-xs text-slate-500">
            <span>Showing {start}–{end} of {page.total.toLocaleString()} events</span>
            <span>Newest first</span>
          </div>
          <div className="space-y-3">
            {page.events.map((event) => (
              <Card key={event.id}>
                <CardHeader
                  title={LABELS[event.action] ?? event.action.replace(/_/g, ' ')}
                  description={`${event.actor_username || event.target_username || 'Unknown account'}${event.actor_role ? ` · ${event.actor_role.replace(/_/g, ' ')}` : ''} · ${formatDate(event.created_at)}`}
                  actions={<Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>}
                />
                <CardBody className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
                  {event.target_username && event.target_username !== event.actor_username && <span>Account: {event.target_username}</span>}
                  {event.tenant_id && <span>Tenant: {event.tenant_id}</span>}
                  {event.resource_type && <span>{event.resource_type.replace(/_/g, ' ')}{event.resource_id ? ` · ${event.resource_id}` : ''}</span>}
                  {describeDetails(event.details) && <span>{describeDetails(event.details)}</span>}
                  {event.action === 'login' && event.outcome === 'failure' && <span>Invalid credentials</span>}
                </CardBody>
              </Card>
            ))}
          </div>
          <div className="mt-4 flex items-center justify-between">
            <Button variant="secondary" disabled={page.offset === 0 || state.loading} icon={<ChevronLeft className="h-4 w-4" />} onClick={() => setFilters((value) => ({ ...value, offset: Math.max(0, (value.offset ?? 0) - PAGE_SIZE) }))}>Previous</Button>
            <span className="text-xs text-slate-500">Page {Math.floor(page.offset / page.limit) + 1} of {Math.max(1, Math.ceil(page.total / page.limit))}</span>
            <Button variant="secondary" disabled={page.offset + page.events.length >= page.total || state.loading} icon={<ChevronRight className="h-4 w-4" />} onClick={() => setFilters((value) => ({ ...value, offset: (value.offset ?? 0) + PAGE_SIZE }))}>Next</Button>
          </div>
        </>
      )}
    </div>
  )
}
