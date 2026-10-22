import { useState } from 'react'
import { AlertTriangle, MessageSquareWarning, Send, Trash2 } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { COMPLAINT_PRIORITIES, COMPLAINT_STATUSES, conversationsApi, stripRoute } from '@/lib/conversations'
import { formatDate, relativeTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const FILTERS = ['all', ...COMPLAINT_STATUSES]

const SELECT =
  'rounded-lg bg-surface-raised px-2.5 py-1.5 text-xs text-slate-200 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500'

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  open: 'danger',
  in_progress: 'warning',
  awaiting_info: 'accent',
  resolved: 'success',
  closed: 'muted',
}

const PRIORITY_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  low: 'muted',
  normal: 'neutral',
  high: 'warning',
  urgent: 'danger',
}

/**
 * Complaints raised through the bot. Reviewing is open to anyone with
 * `view_complaints`; changing status, replying or deleting needs
 * `manage_complaints`.
 */
export function ComplaintsPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()

  const [status, setStatus] = useState('all')
  const [selected, setSelected] = useState<string | null>(null)
  const canManage = can('manage_complaints')

  const state = useAsync(
    (signal) => conversationsApi.complaints(tenantId, { status: status === 'all' ? undefined : status }, signal),
    [tenantId, status],
  )

  const complaints = state.data?.complaints ?? []
  const active = complaints.find((c) => c.ticket_id === selected) ?? null

  const refresh = () => state.reload()

  const patch = async (body: { status?: string; priority?: string; assigned_to?: string }) => {
    if (!active) return
    const result = await action.run(() => conversationsApi.updateComplaint(tenantId, active.ticket_id, body))
    if (result) {
      toast.push('Complaint updated')
      refresh()
    }
  }

  const remove = async () => {
    if (!active) return
    if (!window.confirm(`Delete complaint ${active.ticket_id}? This cannot be undone.`)) return
    const result = await action.run(() => conversationsApi.deleteComplaint(tenantId, active.ticket_id))
    if (result) {
      toast.push('Complaint deleted')
      setSelected(null)
      refresh()
    }
  }

  const reply = async (message: string, resolve: boolean) => {
    if (!active) return false
    const result = await action.run(() =>
      conversationsApi.replyComplaint(tenantId, active.ticket_id, message, resolve ? 'resolved' : undefined),
    )
    if (result) {
      toast.push('Reply sent')
      refresh()
      return true
    }
    return false
  }

  return (
    <div>
      <PageHeader
        title="Complaints"
        description="Issues customers raised through the bot. Reply to reopen the conversation, or move the ticket through to resolved."
        meta={
          state.data && (
            <>
              <Badge tone={state.data.open_count ? 'danger' : 'success'}>
                {state.data.open_count} open
              </Badge>
              <Badge tone="muted">{state.data.count} shown</Badge>
            </>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {FILTERS.map((filter) => (
          <button
            key={filter}
            type="button"
            onClick={() => {
              setStatus(filter)
              setSelected(null)
            }}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition',
              status === filter
                ? 'bg-accent-100 text-accent-800'
                : 'text-slate-400 hover:bg-surface-panel hover:text-slate-200',
            )}
          >
            {filter.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <Card className="overflow-hidden">
          <CardHeader title="Tickets" icon={<MessageSquareWarning className="h-4 w-4" />} />
          {state.loading && !complaints.length ? (
            <LoadingBlock label="Loading complaints…" />
          ) : state.error ? (
            <CardBody>
              <Alert tone="danger" title="Could not load">
                {state.error}
              </Alert>
            </CardBody>
          ) : complaints.length === 0 ? (
            <EmptyState title="No complaints" description="Nothing matches this filter." />
          ) : (
            <ul className="max-h-[70vh] divide-y divide-surface-line overflow-y-auto scroll-thin">
              {complaints.map((item) => (
                <li key={item.ticket_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.ticket_id)}
                    className={cn(
                      'w-full px-4 py-3 text-left transition',
                      item.ticket_id === selected ? 'bg-accent-50' : 'hover:bg-surface-panel',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100">
                        {item.subject || item.complaint_type || item.ticket_id}
                      </span>
                      <span className="shrink-0 text-2xs text-slate-500">{relativeTime(item.created_at)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-2xs text-slate-500">{item.ticket_id}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge tone={STATUS_TONE[item.status] ?? 'neutral'}>{item.status.replace(/_/g, ' ')}</Badge>
                      <Badge tone={PRIORITY_TONE[item.priority] ?? 'neutral'}>{item.priority}</Badge>
                      {item.assigned_to && <Badge tone="accent">{item.assigned_to}</Badge>}
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex min-h-[24rem] flex-col">
          {!active ? (
            <EmptyState
              title="Pick a ticket"
              description="Select a complaint to read it and act on it."
              icon={<MessageSquareWarning className="h-6 w-6" />}
            />
          ) : (
            <>
              <CardHeader
                title={active.subject || active.complaint_type || active.ticket_id}
                description={`${active.ticket_id} · ${active.wa_id || 'no customer'} · raised ${formatDate(active.created_at)}`}
                icon={<AlertTriangle className="h-4 w-4" />}
                actions={
                  canManage && (
                    <Button size="sm" variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={remove} loading={action.busy}>
                      Delete
                    </Button>
                  )
                }
              />

              <CardBody className="flex-1 space-y-4 overflow-y-auto scroll-thin">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={STATUS_TONE[active.status] ?? 'neutral'}>{active.status.replace(/_/g, ' ')}</Badge>
                  <Badge tone={PRIORITY_TONE[active.priority] ?? 'neutral'}>{active.priority} priority</Badge>
                  {active.complaint_type && <Badge tone="neutral">{active.complaint_type}</Badge>}
                </div>

                <div className="rounded-xl bg-surface-panel p-3.5 text-sm leading-relaxed text-slate-200 ring-1 ring-inset ring-surface-line">
                  {active.description || 'No description recorded.'}
                </div>

                {active.last_user_message && (
                  <p className="text-xs text-slate-500">
                    Last from customer: {stripRoute(active.last_user_message)}
                  </p>
                )}

                {canManage && (
                  <div className="flex flex-wrap items-center gap-3">
                    <label className="flex items-center gap-2 text-xs text-slate-400">
                      Status
                      <select value={active.status} onChange={(e) => patch({ status: e.target.value })} className={SELECT}>
                        {COMPLAINT_STATUSES.map((s) => (
                          <option key={s} value={s}>
                            {s.replace(/_/g, ' ')}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-400">
                      Priority
                      <select value={active.priority} onChange={(e) => patch({ priority: e.target.value })} className={SELECT}>
                        {COMPLAINT_PRIORITIES.map((p) => (
                          <option key={p} value={p}>
                            {p}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="flex items-center gap-2 text-xs text-slate-400">
                      Assignee
                      <Input
                        defaultValue={active.assigned_to ?? ''}
                        placeholder="unassigned"
                        className="h-[30px] w-40 py-0 text-xs"
                        onBlur={(e) => {
                          if (e.target.value !== (active.assigned_to ?? '')) patch({ assigned_to: e.target.value })
                        }}
                      />
                    </label>
                  </div>
                )}
              </CardBody>

              {canManage && active.wa_id && (
                <ComplaintReply busy={action.busy} onSend={reply} />
              )}
            </>
          )}
        </Card>
      </div>
    </div>
  )
}

function ComplaintReply({
  busy,
  onSend,
}: {
  busy: boolean
  onSend: (message: string, resolve: boolean) => Promise<boolean>
}) {
  const [draft, setDraft] = useState('')
  const [resolve, setResolve] = useState(false)

  const send = async () => {
    const message = draft.trim()
    if (!message) return
    if (await onSend(message, resolve)) {
      setDraft('')
      setResolve(false)
    }
  }

  return (
    <div className="border-t border-surface-line p-4">
      <Textarea
        rows={2}
        value={draft}
        placeholder="Reply to the customer…"
        onChange={(e) => setDraft(e.target.value)}
      />
      <div className="mt-2 flex items-center justify-between gap-2">
        <label className="flex items-center gap-2 text-xs text-slate-400">
          <input
            type="checkbox"
            checked={resolve}
            onChange={(e) => setResolve(e.target.checked)}
            className="rounded border-surface-line bg-surface-raised text-accent-600 focus:ring-accent-500"
          />
          Mark resolved after sending
        </label>
        <Button variant="primary" icon={<Send className="h-4 w-4" />} loading={busy} onClick={send} disabled={!draft.trim()}>
          Send reply
        </Button>
      </div>
    </div>
  )
}
