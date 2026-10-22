import { useMemo, useState } from 'react'
import { Bot, History, MessageSquare, Search } from 'lucide-react'
import { useAsync } from '@/lib/hooks'
import { conversationsApi, stripRoute } from '@/lib/conversations'
import { formatDate, pluralise, relativeTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import type { ChatTurn } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

const WINDOWS = [
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
  { value: 0, label: 'All time' },
]

interface Thread {
  waId: string
  name: string
  lastAt: string
  turns: ChatTurn[]
}

/**
 * Chat history is the record of everything the bot and agents have said: a read
 * only view for looking back, with a day window and a search box. Grouped by
 * customer so a long tail of turns reads as conversations.
 */
export function ChatHistoryPanel({ tenantId }: { tenantId: string }) {
  const [days, setDays] = useState(30)
  const [draft, setDraft] = useState('')
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<string | null>(null)

  const state = useAsync(
    (signal) =>
      conversationsApi.history(tenantId, { days: days || undefined, search: search || undefined, limit: 500 }, signal),
    [tenantId, days, search],
  )

  const threads = useMemo<Thread[]>(() => {
    const map = new Map<string, Thread>()
    for (const row of state.data ?? []) {
      const existing = map.get(row.wa_id)
      if (existing) {
        existing.turns.push(row)
        if (row.created_at > existing.lastAt) existing.lastAt = row.created_at
      } else {
        map.set(row.wa_id, {
          waId: row.wa_id,
          name: row.sender_name || row.wa_id,
          lastAt: row.created_at,
          turns: [row],
        })
      }
    }
    return [...map.values()].sort((a, b) => b.lastAt.localeCompare(a.lastAt))
  }, [state.data])

  const active = threads.find((t) => t.waId === selected) ?? null
  const totalTurns = (state.data ?? []).length

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="Chat history"
        description="Every recorded exchange with this tenant's customers — what the bot answered and what agents said."
        meta={
          state.data && (
            <>
              <Badge tone="accent">{pluralise(totalTurns, 'turn')}</Badge>
              <Badge tone="muted">{pluralise(threads.length, 'conversation')}</Badge>
            </>
          )
        }
        actions={
          <form
            className="flex items-center gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              setSearch(draft.trim())
            }}
          >
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Search messages…"
                className="w-56 pl-9"
              />
            </div>
            <select
              value={days}
              onChange={(e) => setDays(Number(e.target.value))}
              className="h-[38px] rounded-lg bg-surface-raised px-3 text-sm text-slate-200 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
            >
              {WINDOWS.map((w) => (
                <option key={w.value} value={w.value}>
                  {w.label}
                </option>
              ))}
            </select>
          </form>
        }
      />

      {/*
        Two panes, always side by side. Both grid tracks are `minmax(0, …)` so
        a long message can never stretch the transcript column past the page,
        and the single `minmax(0, 1fr)` row keeps both cards exactly as tall as
        the pane — the lists scroll inside them, the page does not.
      */}
      <div className="grid min-h-0 flex-1 grid-cols-[minmax(0,13rem)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] gap-4 sm:grid-cols-[minmax(0,16rem)_minmax(0,1fr)] lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
        <Card className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          <CardHeader title="Conversations" icon={<History className="h-4 w-4" />} />
          {state.loading && !threads.length ? (
            <LoadingBlock label="Loading history…" />
          ) : state.error ? (
            <CardBody>
              <Alert tone="danger" title="Could not load">
                {state.error}
              </Alert>
            </CardBody>
          ) : threads.length === 0 ? (
            <EmptyState className="flex-1" title="No history" description="Nothing matches this window." />
          ) : (
            <ul className="min-h-0 flex-1 divide-y divide-surface-line overflow-y-auto overflow-x-hidden scroll-overlay">
              {threads.map((thread) => (
                <li key={thread.waId}>
                  <button
                    type="button"
                    onClick={() => setSelected(thread.waId)}
                    className={cn(
                      'w-full px-4 py-3 text-left transition',
                      thread.waId === selected ? 'bg-accent-50' : 'hover:bg-surface-panel',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100">
                        {thread.name}
                      </span>
                      <span className="shrink-0 text-2xs text-slate-500">{relativeTime(thread.lastAt)}</span>
                    </div>
                    <p className="mt-1 text-2xs text-slate-600">
                      {pluralise(thread.turns.length, 'turn')} · {formatDate(thread.lastAt)}
                    </p>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex min-h-0 min-w-0 flex-col overflow-hidden">
          {!active ? (
            <EmptyState
              className="flex-1"
              title="Pick a conversation"
              description="Select a customer to read the full transcript."
              icon={<MessageSquare className="h-6 w-6" />}
            />
          ) : (
            <>
              <CardHeader
                title={active.name}
                description={`${active.waId} · ${pluralise(active.turns.length, 'turn')} in this window`}
                icon={<Bot className="h-4 w-4" />}
              />
              <CardBody className="min-h-0 flex-1 space-y-3 overflow-y-auto overflow-x-hidden break-anywhere scroll-overlay">
                {[...active.turns]
                  .sort((a, b) => a.created_at.localeCompare(b.created_at))
                  .map((turn) => (
                    <div key={turn.id} className="space-y-1.5">
                      {stripRoute(turn.message) && (
                        <div className="flex justify-start">
                          <div className="min-w-0 max-w-[80%] rounded-xl bg-surface-panel px-3 py-2 text-sm text-slate-200 ring-1 ring-inset ring-surface-line">
                            {stripRoute(turn.message)}
                            <span className="mt-1 block text-2xs text-slate-600">{formatDate(turn.created_at)}</span>
                          </div>
                        </div>
                      )}
                      {turn.response && (
                        <div className="flex justify-end">
                          <div
                            className={cn(
                              'min-w-0 max-w-[80%] rounded-xl px-3 py-2 text-sm ring-1 ring-inset',
                              turn.route === 'agent'
                                ? 'bg-accent-600 text-white ring-accent-600'
                                : 'bg-accent-50 text-accent-900 ring-accent-200',
                            )}
                          >
                            {turn.response}
                            <span className="mt-1 block text-2xs opacity-70">
                              {turn.route === 'agent' ? 'agent' : `bot · ${turn.route}`}
                            </span>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
              </CardBody>
            </>
          )}
        </Card>
      </div>
    </div>
  )
}
