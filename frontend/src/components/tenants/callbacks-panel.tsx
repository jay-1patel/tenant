import { useState } from 'react'
import { CalendarCheck, CheckCircle2, PhoneCall, Plus, Video, XCircle } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import {
  CALLBACK_PRIORITIES,
  CALLBACK_STATUSES,
  CALLBACK_TYPES,
  callbacksApi,
  type Callback,
  type CallbackInput,
} from '@/lib/callbacks'
import { formatDate, relativeTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const FILTERS = ['all', ...CALLBACK_STATUSES]

const SELECT =
  'rounded-lg bg-surface-raised px-2.5 py-1.5 text-xs text-slate-200 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500'

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  pending: 'warning',
  confirmed: 'accent',
  scheduled: 'accent',
  in_progress: 'neutral',
  completed: 'success',
  cancelled: 'muted',
  no_show: 'danger',
}

const PRIORITY_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  low: 'muted',
  medium: 'neutral',
  high: 'warning',
  urgent: 'danger',
}

const EMPTY_FORM: CallbackInput = {
  customer_name: '',
  wa_id: '',
  callback_type: 'general',
  priority: 'medium',
  purpose: '',
  customer_phone: '',
  preferred_date: '',
  preferred_time: '',
  additional_info: '',
}

/** True while the callback can still be acted on. */
const OPEN = new Set(['pending', 'confirmed', 'scheduled', 'in_progress'])

/**
 * Callback requests customers raise through the bot, and the agent-side
 * lifecycle: schedule a Google Meet, mark the call done, or cancel.
 */
export function CallbacksPanel({ tenantId }: { tenantId: string }) {
  const toast = useToast()
  const action = useAction()
  const createAction = useAction()

  const [status, setStatus] = useState('all')
  const [selected, setSelected] = useState<string | null>(null)
  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState<CallbackInput>(EMPTY_FORM)
  const [notes, setNotes] = useState('')
  const [schedule, setSchedule] = useState({ agent_name: '', agent_id: '', start: '', end: '' })

  const state = useAsync(
    (signal) => callbacksApi.list(tenantId, { status: status === 'all' ? undefined : status }, signal),
    [tenantId, status],
  )

  const callbacks = state.data?.callbacks ?? []
  const active: Callback | null = callbacks.find((c) => c.id === selected) ?? null
  const refresh = () => state.reload()

  const openCount = callbacks.filter((c) => OPEN.has(c.status)).length

  const update = (patch: Partial<CallbackInput>) => setForm((f) => ({ ...f, ...patch }))

  const create = async () => {
    if (!form.customer_name.trim() || !form.wa_id.trim()) return
    const result = await createAction.run(() => callbacksApi.create(tenantId, form), 'Callback created')
    if (result) {
      setForm(EMPTY_FORM)
      setShowForm(false)
      refresh()
    }
  }

  const cancel = async () => {
    if (!active) return
    if (!window.confirm(`Cancel the callback from ${active.customer_name}? The customer can be notified.`)) return
    const result = await action.run(() => callbacksApi.cancel(tenantId, active.id), 'Callback cancelled')
    if (result) refresh()
  }

  const complete = async () => {
    if (!active) return
    const result = await action.run(
      () => callbacksApi.complete(tenantId, active.id, notes),
      'Callback completed',
    )
    if (result) {
      setNotes('')
      refresh()
    }
  }

  const book = async () => {
    if (!active) return
    if (!schedule.agent_name.trim() || !schedule.start || !schedule.end) return
    const result = await action.run(
      () =>
        callbacksApi.schedule(tenantId, active.id, {
          agent_id: schedule.agent_id.trim() || schedule.agent_name.trim(),
          agent_name: schedule.agent_name.trim(),
          start_time: new Date(schedule.start).toISOString(),
          end_time: new Date(schedule.end).toISOString(),
        }),
      'Callback scheduled — meet link created',
    )
    if (result) {
      setSchedule({ agent_name: '', agent_id: '', start: '', end: '' })
      refresh()
    }
  }

  return (
    <div>
      <PageHeader
        title="Callbacks"
        description="Call-back requests customers raise through the bot. Schedule them with a Google Meet link, mark them done, or cancel."
        meta={
          state.data && (
            <>
              <Badge tone={openCount ? 'warning' : 'success'}>{openCount} open</Badge>
              <Badge tone="muted">{state.data.total_count} total</Badge>
            </>
          )
        }
        actions={
          <Button size="sm" variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setShowForm((v) => !v)}>
            New callback
          </Button>
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

      {showForm && (
        <Card className="mb-4">
          <CardHeader title="New callback request" icon={<PhoneCall className="h-4 w-4" />} />
          <CardBody className="grid gap-3 sm:grid-cols-2">
            <Input
              label="Customer name"
              value={form.customer_name}
              onChange={(e) => update({ customer_name: e.target.value })}
              placeholder="Jane Doe"
            />
            <Input
              label="WhatsApp number"
              value={form.wa_id}
              onChange={(e) => update({ wa_id: e.target.value })}
              placeholder="919876543210"
            />
            <Input
              label="Phone (optional)"
              value={form.customer_phone}
              onChange={(e) => update({ customer_phone: e.target.value })}
              placeholder="+91 98765 43210"
            />
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Type
              <select
                value={form.callback_type}
                onChange={(e) => update({ callback_type: e.target.value })}
                className={SELECT}
              >
                {CALLBACK_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t.replace(/_/g, ' ')}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-slate-400">
              Priority
              <select value={form.priority} onChange={(e) => update({ priority: e.target.value })} className={SELECT}>
                {CALLBACK_PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            </label>
            <Input
              label="Preferred date"
              type="date"
              value={form.preferred_date ?? ''}
              onChange={(e) => update({ preferred_date: e.target.value })}
            />
            <Input
              label="Preferred time"
              value={form.preferred_time ?? ''}
              onChange={(e) => update({ preferred_time: e.target.value })}
              placeholder="10:00 or 10:00-11:00"
            />
            <div className="sm:col-span-2">
              <Input
                label="Purpose"
                value={form.purpose}
                onChange={(e) => update({ purpose: e.target.value })}
                placeholder="What should the call be about?"
              />
            </div>
            <div className="sm:col-span-2">
              <Textarea
                label="Additional info"
                value={form.additional_info}
                onChange={(e) => update({ additional_info: e.target.value })}
                placeholder="Context from the customer…"
              />
            </div>
            {(createAction.error || action.error) && (
              <div className="sm:col-span-2">
                <Alert tone="danger" title="Action failed">
                  {createAction.error || action.error}
                </Alert>
              </div>
            )}
            <div className="flex items-center gap-2 sm:col-span-2">
              <Button variant="primary" size="sm" loading={createAction.busy} onClick={create}>
                Create
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setShowForm(false)}>
                Discard
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {action.error && !showForm && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_1fr]">
        <Card className="overflow-hidden">
          <CardHeader title="Requests" icon={<PhoneCall className="h-4 w-4" />} />
          {state.loading && !callbacks.length ? (
            <LoadingBlock label="Loading callbacks…" />
          ) : state.error ? (
            <CardBody>
              <Alert tone="danger" title="Could not load">
                {state.error}
              </Alert>
            </CardBody>
          ) : callbacks.length === 0 ? (
            <EmptyState title="No callbacks" description="Nothing matches this filter." />
          ) : (
            <ul className="max-h-[70vh] divide-y divide-surface-line overflow-y-auto scroll-thin">
              {callbacks.map((item) => (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.id)}
                    className={cn(
                      'w-full px-4 py-3 text-left transition',
                      item.id === selected ? 'bg-accent-50' : 'hover:bg-surface-panel',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100">
                        {item.customer_name || item.wa_id}
                      </span>
                      <span className="shrink-0 text-2xs text-slate-500">{relativeTime(item.created_at)}</span>
                    </div>
                    <p className="mt-0.5 truncate text-2xs text-slate-500">{item.wa_id}</p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                      <Badge tone={STATUS_TONE[item.status] ?? 'neutral'}>{item.status.replace(/_/g, ' ')}</Badge>
                      <Badge tone={PRIORITY_TONE[item.priority] ?? 'neutral'}>{item.priority}</Badge>
                      {item.meet_link && (
                        <Badge tone="accent">
                          <Video className="mr-1 h-3 w-3" />
                          meet
                        </Badge>
                      )}
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
              title="Pick a request"
              description="Select a callback to read it and act on it."
              icon={<PhoneCall className="h-6 w-6" />}
            />
          ) : (
            <>
              <CardHeader
                title={active.customer_name || active.wa_id}
                description={`${active.wa_id} · raised ${formatDate(active.created_at)}`}
                icon={<PhoneCall className="h-4 w-4" />}
              />
              <CardBody className="flex-1 space-y-4 overflow-y-auto scroll-thin">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={STATUS_TONE[active.status] ?? 'neutral'}>{active.status.replace(/_/g, ' ')}</Badge>
                  <Badge tone={PRIORITY_TONE[active.priority] ?? 'neutral'}>{active.priority} priority</Badge>
                  <Badge tone="neutral">{active.callback_type.replace(/_/g, ' ')}</Badge>
                  {active.assigned_agent_name && <Badge tone="accent">{active.assigned_agent_name}</Badge>}
                </div>

                <div className="rounded-xl bg-surface-panel p-3.5 text-sm leading-relaxed text-slate-200 ring-1 ring-inset ring-surface-line">
                  {active.purpose || active.additional_info || 'No purpose recorded.'}
                </div>

                <div className="grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
                  <p>
                    Preferred:{' '}
                    <span className="text-slate-200">
                      {[active.preferred_date, active.preferred_time].filter(Boolean).join(' ') || 'any time'}
                    </span>
                  </p>
                  <p>
                    Phone: <span className="text-slate-200">{active.customer_phone || '—'}</span>
                  </p>
                  <p>
                    Scheduled:{' '}
                    <span className="text-slate-200">
                      {active.scheduled_start_time ? formatDate(active.scheduled_start_time) : 'not yet'}
                    </span>
                  </p>
                  <p>
                    Updated: <span className="text-slate-200">{relativeTime(active.updated_at)}</span>
                  </p>
                </div>

                {active.meet_link && (
                  <a
                    href={active.meet_link}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-2 text-sm font-medium text-accent-300 hover:underline"
                  >
                    <Video className="h-4 w-4" />
                    Open Google Meet
                  </a>
                )}

                {OPEN.has(active.status) && (
                  <div className="space-y-3 rounded-xl bg-surface-panel p-3.5 ring-1 ring-inset ring-surface-line">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                      Schedule with Google Meet
                    </p>
                    <div className="grid gap-3 sm:grid-cols-2">
                      <Input
                        label="Agent name"
                        value={schedule.agent_name}
                        onChange={(e) => setSchedule((s) => ({ ...s, agent_name: e.target.value }))}
                        placeholder="Agent handling the call"
                      />
                      <Input
                        label="Agent ID (optional)"
                        value={schedule.agent_id}
                        onChange={(e) => setSchedule((s) => ({ ...s, agent_id: e.target.value }))}
                        placeholder="Defaults to the name"
                      />
                      <Input
                        label="Start"
                        type="datetime-local"
                        value={schedule.start}
                        onChange={(e) => setSchedule((s) => ({ ...s, start: e.target.value }))}
                      />
                      <Input
                        label="End"
                        type="datetime-local"
                        value={schedule.end}
                        onChange={(e) => setSchedule((s) => ({ ...s, end: e.target.value }))}
                      />
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<CalendarCheck className="h-4 w-4" />}
                        loading={action.busy}
                        onClick={book}
                      >
                        Schedule
                      </Button>
                      <Button
                        variant="danger"
                        size="sm"
                        icon={<XCircle className="h-4 w-4" />}
                        loading={action.busy}
                        onClick={cancel}
                      >
                        Cancel request
                      </Button>
                    </div>
                  </div>
                )}

                {OPEN.has(active.status) && (
                  <div className="space-y-3 rounded-xl bg-surface-panel p-3.5 ring-1 ring-inset ring-surface-line">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Complete the call</p>
                    <Textarea
                      label="Meeting notes"
                      value={notes}
                      onChange={(e) => setNotes(e.target.value)}
                      placeholder="Outcome of the call…"
                    />
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<CheckCircle2 className="h-4 w-4" />}
                      loading={action.busy}
                      onClick={complete}
                    >
                      Mark completed
                    </Button>
                  </div>
                )}
              </CardBody>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
