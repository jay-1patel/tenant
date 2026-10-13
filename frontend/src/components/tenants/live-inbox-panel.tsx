import { useEffect, useRef, useState } from 'react'
import {
  Bot,
  CheckCheck,
  Inbox,
  Paperclip,
  RefreshCw,
  Send,
  UserRound,
  Users,
} from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { attachmentsApi, ATTACHMENT_ACCEPT, ATTACHMENT_TYPES_LABEL, MAX_ATTACHMENT_LABEL, type Attachment } from '@/lib/attachments'
import { conversationsApi, stripRoute } from '@/lib/conversations'
import { relativeTime } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { AttachmentChip } from './chat-attachment'

const POLL_MS = 12_000

/**
 * The live inbox: conversations a person has to handle.
 *
 * The queue is every customer of this tenant, handovers first. Taking a
 * conversation over pauses the bot; replying sends as the signed-in agent and
 * keeps the bot paused; resolving hands the customer back to the bot.
 */
export function LiveInboxPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()
  const canInbox = can('view_inbox')

  const [selected, setSelected] = useState<string | null>(null)
  const [showResolved, setShowResolved] = useState(false)

  const state = useAsync(
    (signal) => conversationsApi.inbox(tenantId, showResolved, signal),
    [tenantId, showResolved],
  )
  const agents = useAsync((signal) => conversationsApi.agents(tenantId, signal), [tenantId])

  const thread = useAsync(
    (signal) => (selected ? conversationsApi.thread(tenantId, selected, 300, signal) : Promise.resolve(null)),
    [tenantId, selected],
  )

  // Light polling so new inbound messages surface without a manual refresh.
  useEffect(() => {
    const timer = window.setInterval(() => state.reload(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [state.reload])

  const queue = state.data?.queue ?? []
  const current = queue.find((q) => q.wa_id === selected) ?? null

  useEffect(() => {
    if (!selected && queue.length) setSelected(queue[0].wa_id)
  }, [queue, selected])

  const messages = thread.data?.messages ?? []

  const refresh = () => {
    state.reload()
    thread.reload()
  }

  const setMode = async (mode: 'bot' | 'human') => {
    if (!selected) return
    const result = await action.run(() => conversationsApi.setHandover(tenantId, selected, mode))
    if (result) {
      toast.push(mode === 'human' ? 'Bot paused — you have the conversation' : 'Bot resumed')
      refresh()
    }
  }

  const resolve = async () => {
    if (!selected) return
    const result = await action.run(() => conversationsApi.resolve(tenantId, selected, true))
    if (result) {
      toast.push(result.notified ? 'Resolved — the customer was notified' : 'Resolved')
      refresh()
    }
  }

  const assign = async (agentId: string) => {
    if (!selected || !agentId) return
    const result = await action.run(() => conversationsApi.assign(tenantId, selected, agentId))
    if (result) {
      toast.push(`Assigned to ${agentId}`)
      refresh()
    }
  }

  if (!canInbox) {
    return (
      <div>
        <PageHeader title="Live inbox" />
        <Alert tone="warning" title="Not permitted">
          The inbox needs the <strong>view_inbox</strong> permission.
        </Alert>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Live inbox"
        description="Conversations the bot has handed over, or that a person has taken over. Replying pauses the bot until you resolve."
        meta={
          state.data && (
            <>
              <Badge tone={state.data.handoff_count ? 'warning' : 'neutral'}>
                {state.data.handoff_count} awaiting a person
              </Badge>
              <Badge tone="muted">{state.data.count} conversations</Badge>
            </>
          )
        }
        actions={
          <>
            <Button
              variant="ghost"
              icon={<RefreshCw className={cn('h-4 w-4', state.loading && 'animate-spin')} />}
              onClick={refresh}
            >
              Refresh
            </Button>
            <Button
              variant={showResolved ? 'secondary' : 'ghost'}
              icon={<CheckCheck className="h-4 w-4" />}
              onClick={() => setShowResolved((v) => !v)}
            >
              {showResolved ? 'Hiding nothing' : 'Show resolved'}
            </Button>
          </>
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_1fr]">
        <Card className="overflow-hidden">
          <CardHeader title="Queue" icon={<Inbox className="h-4 w-4" />} />
          {state.loading && !queue.length ? (
            <LoadingBlock label="Loading conversations…" />
          ) : state.error ? (
            <CardBody>
              <Alert tone="danger" title="Could not load">
                {state.error}
              </Alert>
            </CardBody>
          ) : queue.length === 0 ? (
            <EmptyState title="Nothing waiting" description="No customer conversations for this tenant yet." />
          ) : (
            <ul className="max-h-[70vh] divide-y divide-surface-line overflow-y-auto scroll-thin">
              {queue.map((item) => (
                <li key={item.wa_id}>
                  <button
                    type="button"
                    onClick={() => setSelected(item.wa_id)}
                    className={cn(
                      'w-full px-4 py-3 text-left transition',
                      item.wa_id === selected ? 'bg-accent-50' : 'hover:bg-surface-panel',
                    )}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-100">
                        {item.name || item.wa_id}
                      </span>
                      <span className="shrink-0 text-2xs text-slate-500">
                        {relativeTime(item.last_message_at)}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-500">{stripRoute(item.last_message)}</p>
                    <div className="mt-1.5 flex items-center gap-1.5">
                      {item.handover_mode === 'human' ? (
                        <Badge tone="warning">person</Badge>
                      ) : (
                        <Badge tone="muted">bot</Badge>
                      )}
                      {item.assigned_agent_id && <Badge tone="accent">{item.assigned_agent_id}</Badge>}
                      <span className="text-2xs text-slate-600">{item.turns} turns</span>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex min-h-[24rem] flex-col">
          {!selected || !current ? (
            <EmptyState
              title="Pick a conversation"
              description="Select a customer on the left to read the transcript and reply."
            />
          ) : (
            <>
              <CardHeader
                title={current.name || current.wa_id}
                description={`${current.wa_id} · ${current.turns} turns · last activity ${relativeTime(current.last_message_at)}`}
                icon={current.handover_mode === 'human' ? <UserRound className="h-4 w-4" /> : <Bot className="h-4 w-4" />}
                actions={
                  <>
                    {current.handover_mode === 'human' ? (
                      <Button size="sm" variant="secondary" onClick={() => setMode('bot')} loading={action.busy}>
                        Return to bot
                      </Button>
                    ) : (
                      <Button size="sm" variant="primary" onClick={() => setMode('human')} loading={action.busy}>
                        Take over
                      </Button>
                    )}
                    <Button size="sm" variant="ghost" icon={<CheckCheck className="h-4 w-4" />} onClick={resolve} loading={action.busy}>
                      Resolve
                    </Button>
                  </>
                }
              />

              <CardBody className="flex-1 space-y-3 overflow-y-auto scroll-thin">
                {thread.loading ? (
                  <LoadingBlock label="Loading transcript…" />
                ) : thread.error ? (
                  <Alert tone="danger" title="Could not load transcript">
                    {thread.error}
                  </Alert>
                ) : messages.length === 0 ? (
                  <p className="py-8 text-center text-sm text-slate-500">No messages recorded.</p>
                ) : (
                  messages
                    .filter((turn) => stripRoute(turn.message) || turn.response)
                    .map((turn) => (
                      <div key={turn.id} className="space-y-1.5">
                        {stripRoute(turn.message) && (
                          <div className="flex justify-start">
                            <div className="max-w-[80%] rounded-xl bg-surface-panel px-3 py-2 text-sm text-slate-200 ring-1 ring-inset ring-surface-line">
                              {stripRoute(turn.message)}
                              <span className="mt-1 block text-2xs text-slate-600">
                                {turn.created_at}
                              </span>
                            </div>
                          </div>
                        )}
                        {turn.response && (
                          <div className="flex justify-end">
                            <div
                              className={cn(
                                'max-w-[80%] rounded-xl px-3 py-2 text-sm ring-1 ring-inset',
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
                    ))
                )}
              </CardBody>

              <Composer
                busy={action.busy}
                onUpload={(file) => attachmentsApi.upload(tenantId, file, 'inbox')}
                onSend={async (message, attachment) => {
                  const result = await action.run(() =>
                    conversationsApi.reply(tenantId, selected, message, attachment),
                  )
                  if (result) {
                    toast.push('Reply sent')
                    refresh()
                    return true
                  }
                  return false
                }}
              />
            </>
          )}
        </Card>
      </div>

      {selected && (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-xs text-slate-400">
            <Users className="h-3.5 w-3.5" />
            Assign to
            <select
              value={current?.assigned_agent_id ?? ''}
              onChange={(e) => assign(e.target.value)}
              className="rounded-lg bg-surface-raised px-2 py-1.5 text-xs text-slate-200 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
            >
              <option value="">Unassigned</option>
              {(agents.data ?? []).map((agent) => (
                <option key={agent.agent_id} value={agent.agent_id}>
                  {agent.username}
                  {agent.status !== 'offline' ? ` · ${agent.status}` : ''}
                </option>
              ))}
            </select>
          </label>
        </div>
      )}
    </div>
  )
}

function Composer({
  busy,
  onUpload,
  onSend,
}: {
  busy: boolean
  onUpload: (file: File) => Promise<Attachment>
  onSend: (message: string, attachment: Attachment | null) => Promise<boolean>
}) {
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<Attachment | null>(null)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)

  const pick = async (file: File | undefined) => {
    if (!file) return
    setUploading(true)
    setError(null)
    try {
      setPending(await onUpload(file))
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  const send = async () => {
    const message = draft.trim()
    if (!message && !pending) return
    const ok = await onSend(message, pending)
    if (ok) {
      setDraft('')
      setPending(null)
    }
  }

  return (
    <div className="border-t border-surface-line p-4">
      {error && <p className="mb-2 text-xs text-rose-400">{error}</p>}
      {pending && (
        <div className="mb-2">
          <AttachmentChip attachment={pending} onRemove={() => setPending(null)} />
        </div>
      )}
      <div className="flex items-end gap-2">
        <input
          ref={fileInput}
          type="file"
          className="hidden"
          accept={ATTACHMENT_ACCEPT}
          onChange={(e) => void pick(e.target.files?.[0])}
        />
        <Button
          variant="ghost"
          size="icon"
          icon={<Paperclip className={cn('h-4 w-4', uploading && 'animate-pulse')} />}
          onClick={() => fileInput.current?.click()}
          disabled={uploading}
          title="Attach a file"
          aria-label="Attach a file"
        />
        <div className="flex-1">
          <Textarea
            rows={2}
            value={draft}
            placeholder="Reply as the business… (this pauses the bot)"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void send()
              }
            }}
          />
        </div>
        <Button
          variant="primary"
          icon={<Send className="h-4 w-4" />}
          loading={busy}
          onClick={send}
          disabled={(!draft.trim() && !pending) || uploading}
        >
          Send
        </Button>
      </div>
      <p className="mt-1 text-2xs text-slate-600">
        Ctrl/⌘ + Enter to send. {ATTACHMENT_TYPES_LABEL} · Max {MAX_ATTACHMENT_LABEL} per file.
        Attachments are shared as a link (WhatsApp media sending is off).
      </p>
    </div>
  )
}
