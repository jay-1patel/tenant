import { useState } from 'react'
import { Pencil, Plus, RefreshCw, Send, Trash2 } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import {
  operationsApi,
  type Campaign,
  type CampaignInput,
  type CampaignRecipient,
  type CampaignSegment,
  type CampaignTemplate,
} from '@/lib/operations'
import { timezoneOptions } from '@/lib/profile'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

/** The full engine-owned lifecycle; tones apply to list, table and form. */
const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  draft: 'muted',
  scheduled: 'accent',
  sending: 'warning',
  completed: 'success',
  paused: 'warning',
  failed: 'danger',
  cancelled: 'danger',
  sent: 'success',
}

const CAMPAIGN_TYPES = ['promotional', 'transactional', 'informational'] as const

/** Statuses an admin may set; the rest belong to the broadcast engine. */
const ADMIN_STATUSES = ['draft', 'scheduled', 'paused', 'cancelled'] as const

const AUDIENCES = [
  { value: 'distributors', label: 'Distributors' },
  { value: 'customers', label: 'Customers' },
  { value: 'segments', label: 'Segments' },
] as const

/** Where a template variable can pull its value from at send time. */
const VAR_FIELD_OPTIONS = [
  { value: 'name', label: "Recipient's name" },
  { value: 'phone', label: "Recipient's phone" },
  { value: 'email', label: "Recipient's email" },
  { value: 'city', label: "Recipient's city" },
  { value: 'region', label: "Recipient's region" },
  { value: 'fixed', label: 'A fixed value' },
] as const

type VarMap = Record<string, { source: string; value: string }>

interface CampaignFormShape {
  name: string
  campaign_type: string
  whatsapp_template: string
  audience_type: 'distributors' | 'customers' | 'segments'
  segment_id: number | null
  var_map: VarMap
  var_fallbacks: Record<string, string>
  schedule_mode: 'now' | 'scheduled'
  scheduled_date: string
  scheduled_time: string
  timezone: string
  media_filename: string
  cta_button_text: string
  cta_button_url: string
  status: string
}

/** {{name}} and {name} placeholders in a template body. */
function extractVariables(body: string): string[] {
  const out = new Set<string>()
  const re = /\{\{\s*(\w+)\s*\}\}|\{(\w+)\}/g
  let match: RegExpExecArray | null
  while ((match = re.exec(body))) out.add(match[1] ?? match[2])
  return [...out]
}

function toShape(campaign?: Campaign | null): CampaignFormShape {
  // Stored convention: {name: "{name}"} maps a variable to a recipient field,
  // {name: "Diwali"} is a fixed value.
  const varMap: VarMap = {}
  for (const [key, raw] of Object.entries(campaign?.template_variables ?? {})) {
    const value = typeof raw === 'string' ? raw : JSON.stringify(raw ?? '')
    const field = value.match(/^\{(\w+)\}$/)?.[1]
    varMap[key] = field ? { source: field, value: '' } : { source: 'fixed', value }
  }

  let scheduledDate = ''
  let scheduledTime = ''
  if (campaign?.scheduled_at) {
    const dt = new Date(campaign.scheduled_at)
    if (!Number.isNaN(dt.getTime())) {
      scheduledDate = `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
      scheduledTime = dt.toTimeString().slice(0, 5)
    }
  }

  const cta = (campaign?.buttons ?? []).find(
    (b): b is { type?: string; text?: string; url?: string } =>
      typeof b === 'object' && b !== null && Boolean((b as { text?: string }).text),
  )

  return {
    name: campaign?.name ?? '',
    campaign_type: campaign?.campaign_type || 'promotional',
    whatsapp_template: campaign?.whatsapp_template ?? '',
    audience_type:
      campaign?.audience_type === 'customers' || campaign?.audience_type === 'segments'
        ? campaign.audience_type
        : 'distributors',
    segment_id: campaign?.segment_id ?? null,
    var_map: varMap,
    var_fallbacks: (campaign?.variable_fallbacks ?? {}) as Record<string, string>,
    schedule_mode: campaign?.schedule_mode === 'scheduled' ? 'scheduled' : 'now',
    scheduled_date: scheduledDate,
    scheduled_time: scheduledTime,
    timezone: campaign?.timezone ?? 'Asia/Kolkata',
    media_filename: campaign?.media_filename ?? '',
    cta_button_text: cta?.text ?? '',
    cta_button_url: cta?.url ?? '',
    status: campaign?.status ?? 'draft',
  }
}

/**
 * Broadcast campaigns and their delivery metrics. Reading needs
 * `view_campaigns`; creating, editing and deleting needs `manage_campaigns`.
 */
export function CampaignsPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()
  const canManage = can('manage_campaigns')

  const [editing, setEditing] = useState<Campaign | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [managingTemplates, setManagingTemplates] = useState(false)
  const [managingSegments, setManagingSegments] = useState(false)

  const state = useAsync((signal) => operationsApi.campaigns(tenantId, signal), [tenantId])
  const templatesState = useAsync((signal) => operationsApi.campaignTemplates(tenantId, signal), [tenantId])
  const segmentsState = useAsync((signal) => operationsApi.campaignSegments(tenantId, signal), [tenantId])

  const campaigns = state.data?.campaigns ?? []
  const stats = state.data?.stats
  const templates = templatesState.data?.templates ?? []
  const segments = segmentsState.data?.segments ?? []

  const submit = async (input: CampaignInput) => {
    if (editing) {
      // PUT replaces every column; the form owns all of them now, except
      // list items which pass straight through from the stored campaign.
      const result = await action.run(() =>
        operationsApi.updateCampaign(tenantId, editing.id, {
          ...input,
          list_items: editing.list_items ?? [],
        }),
      )
      if (result) {
        toast.push('Campaign updated')
        setEditing(null)
        state.reload()
      }
      return
    }
    const result = await action.run(() => operationsApi.createCampaign(tenantId, input))
    if (result) {
      toast.push('Campaign created')
      setCreating(false)
      state.reload()
    }
  }

  const remove = async (campaign: Campaign) => {
    const result = await action.run(() => operationsApi.deleteCampaign(tenantId, campaign.id))
    if (result) {
      toast.push('Campaign deleted')
      setConfirmDelete(null)
      if (editing?.id === campaign.id) setEditing(null)
      state.reload()
    }
  }

  const [recipients, setRecipients] = useState<CampaignRecipient[] | null>(null)
  const [picked, setPicked] = useState<Set<string>>(new Set())
  const [recipientSearch, setRecipientSearch] = useState('')
  const [syncing, setSyncing] = useState(false)
  const [sendingTo, setSendingTo] = useState<number | null>(null)

  /** Sync: load everyone (customers + distributors) and pre-select them all. */
  const syncRecipients = async () => {
    setSyncing(true)
    try {
      const data = await operationsApi.campaignRecipients(tenantId)
      setRecipients(data.recipients)
      setPicked(new Set(data.recipients.filter((r) => !r.opted_out).map((r) => r.wa_id)))
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Sync failed')
    } finally {
      setSyncing(false)
    }
  }

  const togglePicked = (waId: string) => {
    setPicked((prev) => {
      const next = new Set(prev)
      if (next.has(waId)) next.delete(waId)
      else next.add(waId)
      return next
    })
  }

  /** Fire the campaign at the currently picked recipients. */
  const sendToSelection = async (campaign: { id: number; name: string }) => {
    if (!picked.size) return
    if (!window.confirm(`Send "${campaign.name}" to ${picked.size} selected recipients?`)) return
    setSendingTo(campaign.id)
    try {
      const result = await operationsApi.sendCampaignSelection(tenantId, campaign.id, [...picked])
      toast.push(
        `Sent to ${result.sent} recipient(s)` +
          (result.failed ? ` — ${result.failed} failed` : '') +
          (result.skipped_opt_out ? ` — ${result.skipped_opt_out} opted out (skipped)` : ''),
      )
      state.reload()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSendingTo(null)
    }
  }

  /** Send the campaign to its entire selected audience. */
  const sendToAudience = async (campaign: { id: number; name: string; audience_type: string }) => {
    if (!window.confirm(`Send "${campaign.name}" to EVERYONE in the ${campaign.audience_type} audience?`)) return
    setSendingTo(campaign.id)
    try {
      const result = await operationsApi.sendCampaign(tenantId, campaign.id)
      toast.push(
        `${result.audience}: sent to ${result.sent} of ${result.targeted}` +
          (result.failed ? ` — ${result.failed} failed` : '') +
          (result.skipped_opt_out ? ` — ${result.skipped_opt_out} opted out (skipped)` : ''),
      )
      state.reload()
    } catch (err) {
      window.alert(err instanceof Error ? err.message : 'Send failed')
    } finally {
      setSendingTo(null)
    }
  }

  const testSend = async (waId: string) => {
    if (!editing) return
    const result = await action.run(() => operationsApi.testSendCampaign(tenantId, editing.id, waId))
    if (result) toast.push(`Test sent to ${result.sent_to}`)
  }

  return (
    <div>
      <PageHeader
        title="Campaigns"
        description="Scheduled and sent broadcast messages, with delivery and reply metrics per campaign."
        actions={
          canManage && !creating && !editing ? (
            <>
              <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setManagingTemplates((v) => !v)}>
                {managingTemplates ? 'Hide templates' : 'Manage templates'}
              </Button>
              <Button variant="secondary" icon={<Plus className="h-4 w-4" />} onClick={() => setManagingSegments((v) => !v)}>
                {managingSegments ? 'Hide segments' : 'Manage segments'}
              </Button>
              <Button
                variant="secondary"
                icon={<RefreshCw className="h-4 w-4" />}
                loading={syncing}
                onClick={syncRecipients}
              >
                {recipients ? `Recipients (${recipients.length})` : 'Sync recipients'}
              </Button>
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                New campaign
              </Button>
            </>
          ) : undefined
        }
        meta={
          stats && (
            <>
              <Badge tone={stats.active_campaigns ? 'accent' : 'muted'}>
                {stats.active_campaigns} active
              </Badge>
              <Badge tone="success">{stats.total_sent_24h} sent (24h)</Badge>
              <Badge tone="muted">{stats.delivery_rate}% delivered</Badge>
              <Badge tone="muted">{stats.reply_rate}% replied</Badge>
            </>
          )
        }
      />

      {managingTemplates && canManage && (
        <TemplatesManager
          tenantId={tenantId}
          templates={templates}
          onChanged={() => {
            templatesState.reload()
            state.reload()
          }}
        />
      )}

      {managingSegments && canManage && (
        <SegmentsManager
          tenantId={tenantId}
          segments={segments}
          onChanged={() => {
            segmentsState.reload()
            state.reload()
          }}
        />
      )}

      {recipients !== null && canManage && (
        <Card className="mb-4">
          <CardHeader
            title={`Recipients (${recipients.length})`}
            description="Everyone from the customer directory and the distributor network. Tick exactly who should receive a campaign, then press Send on it."
            actions={
              <>
                <Button size="sm" variant="ghost" onClick={() => setPicked(new Set(recipients.filter((r) => !r.opted_out).map((r) => r.wa_id)))}>
                  Select all
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setPicked(new Set())}>
                  Clear
                </Button>
              </>
            }
          />
          <CardBody className="space-y-3">
            <Input
              label="Search"
              value={recipientSearch}
              onChange={(e) => setRecipientSearch(e.target.value)}
              placeholder="Name, number or city"
            />
            <p className="text-2xs text-slate-500">{picked.size} selected</p>
            <div className="max-h-72 divide-y divide-surface-line overflow-y-auto scroll-thin">
              {recipients
                .filter((r) => {
                  const needle = recipientSearch.trim().toLowerCase()
                  if (!needle) return true
                  return [r.name, r.wa_id, r.phone, r.city].some((v) => (v || '').toLowerCase().includes(needle))
                })
                .map((r) => (
                  <label key={r.wa_id} className="flex cursor-pointer items-center gap-3 py-2">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-accent-500"
                      checked={picked.has(r.wa_id)}
                      disabled={r.opted_out}
                      onChange={() => togglePicked(r.wa_id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-sm text-slate-100">{r.name}</span>
                      <span className="block truncate text-2xs text-slate-500">
                        {r.wa_id}
                        {r.phone && r.phone !== r.wa_id ? ` · ${r.phone}` : ''}
                        {r.city ? ` · ${r.city}` : ''}
                      </span>
                    </span>
                    <Badge tone={r.source.includes('distributor') ? 'accent' : 'neutral'}>{r.source}</Badge>
                    {r.opted_out && <Badge tone="danger">opted out</Badge>}
                  </label>
                ))}
            </div>
          </CardBody>
        </Card>
      )}

      {(creating || editing) && (
        <CampaignForm
          tenantId={tenantId}
          initial={editing}
          busy={action.busy}
          error={action.error}
          templates={templates}
          segments={segments}
          onCancel={() => {
            setCreating(false)
            setEditing(null)
          }}
          onSubmit={submit}
          onTestSend={testSend}
        />
      )}

      {state.loading && <LoadingBlock label="Reading campaigns…" />}
      {state.error && (
        <Alert tone="danger" title="Could not read campaigns">
          {state.error}
        </Alert>
      )}

      {state.data && campaigns.length === 0 && !creating && !editing && (
        <Card>
          <EmptyState
            title="No campaigns yet"
            description="The campaign will be sent to all contacts included in the selected audience when the schedule fires."
            action={
              canManage && (
                <Button variant="subtle" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                  New campaign
                </Button>
              )
            }
          />
        </Card>
      )}

      {campaigns.length > 0 && (
        <Card>
          <CardBody className="p-0">
            <div className="overflow-x-auto">
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-surface-line text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-2.5 font-medium">Campaign</th>
                    <th className="px-4 py-2.5 font-medium">Audience</th>
                    <th className="px-4 py-2.5 font-medium">Scheduled</th>
                    <th className="px-4 py-2.5 font-medium">Sent</th>
                    <th className="px-4 py-2.5 font-medium">Delivered</th>
                    <th className="px-4 py-2.5 font-medium">Read</th>
                    <th className="px-4 py-2.5 font-medium">Replied</th>
                    <th className="px-4 py-2.5 font-medium">Status</th>
                    {canManage && <th className="px-4 py-2.5" />}
                  </tr>
                </thead>
                <tbody className="divide-y divide-surface-line">
                  {campaigns.map((campaign) => (
                    <tr key={campaign.id} className="align-middle">
                      <td className="px-4 py-2.5">
                        <p className="font-medium text-slate-100">
                          {campaign.name || `Campaign #${campaign.id}`}
                        </p>
                        <p className="text-xs text-slate-500">
                          {campaign.campaign_type || 'campaign'} · {campaign.target_count} targeted
                        </p>
                      </td>
                      <td className="px-4 py-2.5 text-xs text-slate-300">{campaign.audience_type}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-300">
                        {campaign.schedule_mode === 'scheduled' && campaign.scheduled_at
                          ? formatDate(campaign.scheduled_at)
                          : '—'}
                      </td>
                      <td className="px-4 py-2.5 text-xs text-slate-200">{campaign.metrics?.sent ?? 0}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-200">{campaign.metrics?.delivered ?? 0}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-200">{campaign.metrics?.read ?? 0}</td>
                      <td className="px-4 py-2.5 text-xs text-slate-200">{campaign.metrics?.replied ?? 0}</td>
                      <td className="px-4 py-2.5">
                        <Badge tone={STATUS_TONE[campaign.status] ?? 'neutral'}>{campaign.status}</Badge>
                      </td>
                      {canManage && (
                        <td className="px-4 py-2.5">
                          <div className="flex items-center justify-end gap-1">
                            <Button
                              size="sm"
                              variant="subtle"
                              loading={sendingTo === campaign.id}
                              onClick={() => sendToAudience(campaign)}
                            >
                              <Send className="h-3.5 w-3.5" /> Send all
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              disabled={!recipients || picked.size === 0}
                              loading={sendingTo === campaign.id}
                              onClick={() => sendToSelection(campaign)}
                            >
                              <Send className="h-3.5 w-3.5" /> Picked{picked.size ? ` (${picked.size})` : ''}
                            </Button>
                            <Button size="sm" variant="ghost" onClick={() => setEditing(campaign)}>
                              <Pencil className="h-3.5 w-3.5" /> Edit
                            </Button>
                            {confirmDelete === campaign.id ? (
                              <>
                                <Button size="sm" variant="danger" loading={action.busy} onClick={() => remove(campaign)}>
                                  Delete forever
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                className="text-rose-400 hover:text-rose-300"
                                onClick={() => setConfirmDelete(campaign.id)}
                              >
                                <Trash2 className="h-3.5 w-3.5" /> Delete
                              </Button>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardBody>
        </Card>
      )}
    </div>
  )
}

/** WhatsApp templates: what the campaign form's template dropdown offers. */
function TemplatesManager({
  tenantId,
  templates,
  onChanged,
}: {
  tenantId: string
  templates: CampaignTemplate[]
  onChanged: () => void
}) {
  const action = useAction()
  const toast = useToast()
  const [name, setName] = useState('')
  const [category, setCategory] = useState('MARKETING')
  const [body, setBody] = useState('')
  const [language, setLanguage] = useState('en')
  const [header, setHeader] = useState('')
  const [footer, setFooter] = useState('')
  const [params, setParams] = useState('')
  const [touched, setTouched] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const nameMissing = touched && !name.trim()
  const bodyMissing = touched && !body.trim()

  const add = async () => {
    setTouched(true)
    if (!name.trim() || !body.trim()) return
    const result = await action.run(() =>
      operationsApi.createCampaignTemplate(tenantId, {
        name: name.trim(),
        category,
        body: body.trim(),
        language,
        header: header.trim(),
        footer: footer.trim(),
        params: params.split(',').map((v) => v.trim()).filter(Boolean),
      }),
    )
    if (result) {
      toast.push('Template added')
      setName('')
      setBody('')
      setHeader('')
      setFooter('')
      setParams('')
      setTouched(false)
      onChanged()
    }
  }

  const setStatus = async (template: CampaignTemplate, status: 'registered' | 'rejected' | 'pending') => {
    const result = await action.run(() =>
      operationsApi.setCampaignTemplateStatus(tenantId, template.id, status),
    )
    if (result) {
      toast.push(`Template ${status}`)
      onChanged()
    }
  }

  const remove = async (template: CampaignTemplate) => {
    const result = await action.run(() => operationsApi.deleteCampaignTemplate(tenantId, template.id))
    if (result) {
      toast.push('Template deleted')
      setConfirmDelete(null)
      onChanged()
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title="WhatsApp templates"
        description="Approved templates are what campaigns broadcast. Each carries the Meta category and language the campaign type must match."
      />
      <CardBody className="space-y-4">
        {templates.length > 0 ? (
          <div className="divide-y divide-surface-line rounded-lg ring-1 ring-inset ring-surface-line">
            {templates.map((template) => (
              <div key={template.id} className="flex flex-wrap items-start gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-100">
                    {template.name}{' '}
                    <span className="text-xs font-normal text-slate-500">
                      ({template.category} · {template.language})
                    </span>
                  </p>
                  {template.header && (
                    <p className="mt-0.5 text-xs font-medium text-slate-300">{template.header}</p>
                  )}
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-400">{template.body}</p>
                  {template.footer && (
                    <p className="mt-0.5 text-xs italic text-slate-500">{template.footer}</p>
                  )}
                  {template.provider_response && template.status !== 'registered' && (
                    <p className="mt-1 text-xs text-rose-400">Provider: {template.provider_response.slice(0, 160)}</p>
                  )}
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge
                    tone={
                      template.status === 'registered' || template.status === 'already_exists'
                        ? 'success'
                        : template.status === 'rejected' || template.status === 'failed' || template.status === 'error'
                          ? 'danger'
                          : 'muted'
                    }
                  >
                    {template.status}
                  </Badge>
                  {template.status !== 'registered' && template.status !== 'already_exists' && (
                    <Button size="sm" variant="ghost" onClick={() => setStatus(template, 'registered')}>
                      Approve
                    </Button>
                  )}
                  {template.status !== 'rejected' && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-rose-400 hover:text-rose-300"
                      onClick={() => setStatus(template, 'rejected')}
                    >
                      Reject
                    </Button>
                  )}
                  {confirmDelete === template.id ? (
                    <>
                      <Button size="sm" variant="danger" loading={action.busy} onClick={() => remove(template)}>
                        Delete forever
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-rose-400 hover:text-rose-300"
                      onClick={() => setConfirmDelete(template.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Delete
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            No templates yet — add the first one below, then it appears in the campaign form's dropdown.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Template name *"
            value={name}
            error={nameMissing ? 'A template name is required' : undefined}
            onChange={(e) => setName(e.target.value)}
            placeholder="diwali_restock_offer"
          />
          <Select label="Category *" value={category} onChange={(e) => setCategory(e.target.value)}>
            {['MARKETING', 'UTILITY', 'AUTHENTICATION'].map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </Select>
          <Input label="Language" value={language} onChange={(e) => setLanguage(e.target.value)} hint="Meta requires one locale per template (e.g. en, hi, gu)." />
          <Input label="Header (optional)" value={header} onChange={(e) => setHeader(e.target.value)} placeholder="🎉 Diwali Restock Offer" />
          <Input label="Footer (optional)" value={footer} onChange={(e) => setFooter(e.target.value)} placeholder="Reply STOP to unsubscribe" />
          <Input
            label="Sample values (optional)"
            value={params}
            onChange={(e) => setParams(e.target.value)}
            hint="Comma separated, one per placeholder — Meta asks for these during approval."
            placeholder="Rajesh, 20%"
          />
        </div>
        <Textarea
          label="Template body *"
          rows={3}
          value={body}
          error={bodyMissing ? 'A template body is required' : undefined}
          onChange={(e) => setBody(e.target.value)}
          hint="Use {{name}} style placeholders; campaigns map them to each recipient's details."
          placeholder="Hi {{name}}, get {{discount}} off on your Diwali restock."
        />
        <Button variant="primary" loading={action.busy} onClick={add}>
          Add template
        </Button>
        {action.error && <Alert tone="danger" title="Could not save template">{action.error}</Alert>}
      </CardBody>
    </Card>
  )
}

/** Human-readable criteria for a saved segment. */
function criteriaSummary(segment: CampaignSegment): string {
  const c = segment.criteria
  const parts: string[] = []

  const list = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])
  const num = (v: unknown): string | null =>
    typeof v === 'number' ? String(v) : typeof v === 'string' && v.trim() ? v : null

  if (list(c.regions).length) parts.push(`State = ${list(c.regions).join(' / ')}`)
  if (typeof c.city === 'string' && c.city.trim()) parts.push(`City = ${c.city}`)
  if (list(c.tiers).length) parts.push(`Tier: ${list(c.tiers).join(', ')}`)
  if (list(c.product_interests).length) parts.push(`Interests: ${list(c.product_interests).join(', ')}`)
  if (num(c.min_sales_volume)) parts.push(`Sales volume ≥ ₹${Number(c.min_sales_volume).toLocaleString('en-IN')}`)
  if (c.credit_status === 'outstanding') parts.push('Credit: outstanding')
  if (c.credit_status === 'clear') parts.push('Credit: clear')
  if (num(c.min_total_purchases)) parts.push(`Total purchases > ₹${Number(c.min_total_purchases).toLocaleString('en-IN')}`)
  if (num(c.max_total_purchases)) parts.push(`Total purchases < ₹${Number(c.max_total_purchases).toLocaleString('en-IN')}`)
  if (num(c.order_count_min)) parts.push(`Orders ≥ ${c.order_count_min}`)
  if (num(c.order_count_max)) parts.push(`Orders ≤ ${c.order_count_max}`)
  if (num(c.last_order_within_days)) parts.push(`Last order within ${c.last_order_within_days} days`)
  if (num(c.inactive_for_days)) parts.push(`Inactive for ${c.inactive_for_days}+ days`)
  if (num(c.registered_within_days)) parts.push(`Registered in last ${c.registered_within_days} days`)

  const exclusions: string[] = []
  if (list(c.exclude_regions).length) exclusions.push(`State ≠ ${list(c.exclude_regions).join('/')}`)
  if (list(c.exclude_tiers).length) exclusions.push(`Tier ≠ ${list(c.exclude_tiers).join('/')}`)
  if (typeof c.exclude_city === 'string' && c.exclude_city.trim()) exclusions.push(`City ≠ ${c.exclude_city}`)
  if (exclusions.length) parts.push(`excluding ${exclusions.join(', ')}`)
  if (c.match === 'any') parts.push('matching ANY criterion')

  return parts.length ? parts.join(' · ') : 'All opted-in contacts'
}

/** Saved segments: a name, an audience type and the criteria that define it. */
function SegmentsManager({
  tenantId,
  segments,
  onChanged,
}: {
  tenantId: string
  segments: CampaignSegment[]
  onChanged: () => void
}) {
  const action = useAction()
  const toast = useToast()
  const [editing, setEditing] = useState<CampaignSegment | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [touched, setTouched] = useState(false)

  const [name, setName] = useState('')
  const [audienceType, setAudienceType] = useState<'distributors' | 'customers'>('distributors')
  const [match, setMatch] = useState<'all' | 'any'>('all')
  const [regions, setRegions] = useState('')
  const [tiers, setTiers] = useState('')
  const [city, setCity] = useState('')
  const [interests, setInterests] = useState('')
  const [minSalesVolume, setMinSalesVolume] = useState('')
  const [creditStatus, setCreditStatus] = useState<'any' | 'outstanding' | 'clear'>('any')
  const [registeredWithin, setRegisteredWithin] = useState('')
  const [excludeRegions, setExcludeRegions] = useState('')
  const [excludeTiers, setExcludeTiers] = useState('')
  const [excludeCity, setExcludeCity] = useState('')
  const [minPurchases, setMinPurchases] = useState('')
  const [maxPurchases, setMaxPurchases] = useState('')
  const [orderCountMin, setOrderCountMin] = useState('')
  const [orderCountMax, setOrderCountMax] = useState('')
  const [lastOrderWithin, setLastOrderWithin] = useState('')
  const [inactiveFor, setInactiveFor] = useState('')

  const startEdit = (segment: CampaignSegment) => {
    setEditing(segment)
    setTouched(false)
    setName(segment.name)
    setAudienceType(segment.audience_type)
    const c = segment.criteria
    setMatch(c.match === 'any' ? 'any' : 'all')
    setRegions(Array.isArray(c.regions) ? (c.regions as string[]).join(', ') : '')
    setTiers(Array.isArray(c.tiers) ? (c.tiers as string[]).join(', ') : '')
    setCity(typeof c.city === 'string' ? c.city : '')
    setInterests(Array.isArray(c.product_interests) ? (c.product_interests as string[]).join(', ') : '')
    setMinSalesVolume(c.min_sales_volume != null ? String(c.min_sales_volume) : '')
    setCreditStatus(c.credit_status === 'outstanding' || c.credit_status === 'clear' ? c.credit_status : 'any')
    setRegisteredWithin(c.registered_within_days != null ? String(c.registered_within_days) : '')
    setExcludeRegions(Array.isArray(c.exclude_regions) ? (c.exclude_regions as string[]).join(', ') : '')
    setExcludeTiers(Array.isArray(c.exclude_tiers) ? (c.exclude_tiers as string[]).join(', ') : '')
    setExcludeCity(typeof c.exclude_city === 'string' ? c.exclude_city : '')
    setMinPurchases(c.min_total_purchases != null ? String(c.min_total_purchases) : '')
    setMaxPurchases(c.max_total_purchases != null ? String(c.max_total_purchases) : '')
    setOrderCountMin(c.order_count_min != null ? String(c.order_count_min) : '')
    setOrderCountMax(c.order_count_max != null ? String(c.order_count_max) : '')
    setLastOrderWithin(c.last_order_within_days != null ? String(c.last_order_within_days) : '')
    setInactiveFor(c.inactive_for_days != null ? String(c.inactive_for_days) : '')
  }

  const reset = () => {
    setEditing(null)
    setTouched(false)
    setName('')
    setAudienceType('distributors')
    setMatch('all')
    setRegions('')
    setTiers('')
    setCity('')
    setInterests('')
    setMinSalesVolume('')
    setCreditStatus('any')
    setRegisteredWithin('')
    setExcludeRegions('')
    setExcludeTiers('')
    setExcludeCity('')
    setMinPurchases('')
    setMaxPurchases('')
    setOrderCountMin('')
    setOrderCountMax('')
    setLastOrderWithin('')
    setInactiveFor('')
  }

  const nameMissing = touched && !name.trim()

  const criteria = (): Record<string, unknown> => {
    const list = (value: string) => value.split(',').map((v) => v.trim()).filter(Boolean)
    const num = (value: string) => (value.trim() === '' ? undefined : Number(value))

    if (audienceType === 'customers') {
      const out: Record<string, unknown> = {}
      if (num(minPurchases) !== undefined) out.min_total_purchases = num(minPurchases)
      if (num(maxPurchases) !== undefined) out.max_total_purchases = num(maxPurchases)
      if (num(orderCountMin) !== undefined) out.order_count_min = num(orderCountMin)
      if (num(orderCountMax) !== undefined) out.order_count_max = num(orderCountMax)
      if (num(lastOrderWithin) !== undefined) out.last_order_within_days = num(lastOrderWithin)
      if (num(inactiveFor) !== undefined) out.inactive_for_days = num(inactiveFor)
      if (num(registeredWithin) !== undefined) out.registered_within_days = num(registeredWithin)
      return out
    }

    const out: Record<string, unknown> = {}
    if (list(regions).length) out.regions = list(regions)
    if (list(tiers).length) out.tiers = list(tiers)
    if (city.trim()) out.city = city.trim()
    if (list(interests).length) out.product_interests = list(interests)
    if (num(minSalesVolume) !== undefined) out.min_sales_volume = num(minSalesVolume)
    if (creditStatus !== 'any') out.credit_status = creditStatus
    if (num(registeredWithin) !== undefined) out.registered_within_days = num(registeredWithin)
    if (list(excludeRegions).length) out.exclude_regions = list(excludeRegions)
    if (list(excludeTiers).length) out.exclude_tiers = list(excludeTiers)
    if (excludeCity.trim()) out.exclude_city = excludeCity.trim()
    if (match === 'any') out.match = 'any'
    return out
  }

  const save = async () => {
    setTouched(true)
    if (!name.trim()) return
    const body = { name: name.trim(), audience_type: audienceType, criteria: criteria() }
    const result = editing
      ? await action.run(() => operationsApi.updateCampaignSegment(tenantId, editing.id, body))
      : await action.run(() => operationsApi.createCampaignSegment(tenantId, body))
    if (result) {
      toast.push(editing ? 'Segment updated' : 'Segment added')
      reset()
      onChanged()
    }
  }

  const remove = async (segment: CampaignSegment) => {
    const result = await action.run(() => operationsApi.deleteCampaignSegment(tenantId, segment.id))
    if (result) {
      toast.push('Segment deleted')
      setConfirmDelete(null)
      if (editing?.id === segment.id) reset()
      onChanged()
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title="Segments"
        description="Named, reusable audiences. Criteria combine as AND by default (or ANY); contacts who replied STOP are always excluded, and every saved segment shows its live contact count."
      />
      <CardBody className="space-y-4">
        {segments.length > 0 ? (
          <div className="divide-y divide-surface-line rounded-lg ring-1 ring-inset ring-surface-line">
            {segments.map((segment) => (
              <div key={segment.id} className="flex flex-wrap items-start gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-100">{segment.name}</p>
                  <p className="mt-0.5 text-xs text-slate-400">
                    Audience Type: {segment.audience_type === 'customers' ? 'Customer' : 'Distributor'} ·{' '}
                    Criteria: {criteriaSummary(segment)}
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <Badge tone="muted">{segment.target_count} contacts</Badge>
                  <Button size="sm" variant="ghost" onClick={() => startEdit(segment)}>
                    <Pencil className="h-3.5 w-3.5" /> Edit
                  </Button>
                  {confirmDelete === segment.id ? (
                    <>
                      <Button size="sm" variant="danger" loading={action.busy} onClick={() => remove(segment)}>
                        Delete forever
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-rose-400 hover:text-rose-300"
                      onClick={() => setConfirmDelete(segment.id)}
                    >
                      <Trash2 className="h-3.5 w-3.5" /> Delete
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-500">
            No segments yet — create one below, then campaigns can target it.
          </p>
        )}

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Segment Name *"
            value={name}
            error={nameMissing ? 'A segment name is required' : undefined}
            onChange={(e) => setName(e.target.value)}
            placeholder={audienceType === 'customers' ? 'High-Value Customers' : 'Gujarat Distributors'}
          />
          <Select
            label="Audience Type *"
            value={audienceType}
            onChange={(e) => setAudienceType(e.target.value as 'distributors' | 'customers')}
          >
            <option value="distributors">Distributor</option>
            <option value="customers">Customer</option>
          </Select>
        </div>

        {audienceType === 'distributors' ? (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="State / Region"
                value={regions}
                onChange={(e) => setRegions(e.target.value)}
                hint="Comma separated, e.g. Gujarat, Maharashtra"
              />
              <Input label="City" value={city} onChange={(e) => setCity(e.target.value)} placeholder="Ahmedabad" />
              <Input
                label="Tier(s)"
                value={tiers}
                onChange={(e) => setTiers(e.target.value)}
                hint="Comma separated, e.g. Gold, Platinum"
              />
              <Input
                label="Product interests"
                value={interests}
                onChange={(e) => setInterests(e.target.value)}
                hint="Comma separated"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Sales volume ≥ (₹)"
                type="number"
                value={minSalesVolume}
                onChange={(e) => setMinSalesVolume(e.target.value)}
                placeholder="100000"
              />
              <Select
                label="Credit status"
                value={creditStatus}
                onChange={(e) => setCreditStatus(e.target.value as 'any' | 'outstanding' | 'clear')}
              >
                <option value="any">Any</option>
                <option value="outstanding">Has outstanding payments</option>
                <option value="clear">No outstanding payments</option>
              </Select>
              <Input
                label="Registered within (days)"
                type="number"
                value={registeredWithin}
                onChange={(e) => setRegisteredWithin(e.target.value)}
                placeholder="30"
              />
              <Select
                label="Criteria combination"
                value={match}
                onChange={(e) => setMatch(e.target.value as 'all' | 'any')}
                hint="AND = must satisfy every criterion; OR = any one is enough."
              >
                <option value="all">Match ALL (AND)</option>
                <option value="any">Match ANY (OR)</option>
              </Select>
            </div>
            <div>
              <p className="field-label mb-1.5">Exclusions</p>
              <div className="grid gap-4 sm:grid-cols-3">
                <Input
                  label="Except state(s)"
                  value={excludeRegions}
                  onChange={(e) => setExcludeRegions(e.target.value)}
                  hint="Comma separated"
                  placeholder="Maharashtra"
                />
                <Input
                  label="Except tier(s)"
                  value={excludeTiers}
                  onChange={(e) => setExcludeTiers(e.target.value)}
                  hint="Comma separated"
                  placeholder="Bronze"
                />
                <Input
                  label="Except city"
                  value={excludeCity}
                  onChange={(e) => setExcludeCity(e.target.value)}
                  placeholder="Surat"
                />
              </div>
            </div>
          </>
        ) : (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Input
                label="Total purchases > (₹)"
                type="number"
                value={minPurchases}
                onChange={(e) => setMinPurchases(e.target.value)}
                placeholder="10000"
              />
              <Input
                label="Total purchases < (₹)"
                type="number"
                value={maxPurchases}
                onChange={(e) => setMaxPurchases(e.target.value)}
                placeholder="50000"
              />
              <Input
                label="Order count ≥"
                type="number"
                value={orderCountMin}
                onChange={(e) => setOrderCountMin(e.target.value)}
                placeholder="3"
              />
              <Input
                label="Order count ≤"
                type="number"
                value={orderCountMax}
                onChange={(e) => setOrderCountMax(e.target.value)}
                placeholder="20"
              />
            </div>
            <div className="grid gap-4 sm:grid-cols-3">
              <Input
                label="Last order within (days)"
                type="number"
                value={lastOrderWithin}
                onChange={(e) => setLastOrderWithin(e.target.value)}
                placeholder="30"
              />
              <Input
                label="Inactive for (days+)"
                type="number"
                value={inactiveFor}
                onChange={(e) => setInactiveFor(e.target.value)}
                hint="No order in at least this many days."
                placeholder="90"
              />
              <Input
                label="Registered within (days)"
                type="number"
                value={registeredWithin}
                onChange={(e) => setRegisteredWithin(e.target.value)}
                hint="First chatted in the last N days."
                placeholder="30"
              />
            </div>
          </>
        )}

        <div className="flex items-center gap-2">
          <Button variant="primary" loading={action.busy} onClick={save}>
            {editing ? 'Save segment' : 'Add segment'}
          </Button>
          {editing && (
            <Button variant="ghost" onClick={reset}>
              Cancel
            </Button>
          )}
        </div>
        {action.error && <Alert tone="danger" title="Could not save segment">{action.error}</Alert>}
      </CardBody>
    </Card>
  )
}

function CampaignForm({
  initial,
  busy,
  error,
  templates,
  segments,
  tenantId,
  onSubmit,
  onCancel,
  onTestSend,
}: {
  initial: Campaign | null
  busy: boolean
  error: string | null
  tenantId: string
  templates: CampaignTemplate[]
  segments: CampaignSegment[]
  onSubmit: (input: CampaignInput) => void
  onCancel: () => void
  onTestSend: (waId: string) => Promise<void>
}) {
  const [form, setForm] = useState<CampaignFormShape>(() => toShape(initial))
  const [touched, setTouched] = useState(false)
  const [testWaId, setTestWaId] = useState('')
  const [mediaUploading, setMediaUploading] = useState(false)
  const [mediaError, setMediaError] = useState('')

  const set = <K extends keyof CampaignFormShape>(key: K, value: CampaignFormShape[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  // 'registered' / 'already_exists' = the WhatsApp provider accepted it.
  const approvedTemplates = templates.filter(
    (t) => t.status === 'registered' || t.status === 'already_exists',
  )
  const selectedTemplate = approvedTemplates.find((t) => t.name === form.whatsapp_template) ?? null
  const templateVariables = extractVariables(selectedTemplate?.body ?? '')

  const nameMissing = touched && !form.name.trim()
  const templateMissing = touched && !form.whatsapp_template
  const segmentMissing = touched && form.audience_type === 'segments' && !form.segment_id
  const scheduleDateMissing = touched && form.schedule_mode === 'scheduled' && !form.scheduled_date
  const scheduleTimeMissing = touched && form.schedule_mode === 'scheduled' && !form.scheduled_time

  const mediaValid =
    !form.media_filename.trim() || /\.(jpe?g|png|mp4)$/i.test(form.media_filename.trim())

  let ctaValid = true
  let ctaError = ''
  const ctaText = form.cta_button_text.trim()
  const ctaUrl = form.cta_button_url.trim()
  if (ctaText && !ctaUrl) {
    ctaValid = false
    ctaError = 'CTA text needs a URL'
  } else if (ctaUrl && !/^https:\/\//i.test(ctaUrl)) {
    ctaValid = false
    ctaError = 'CTA URL must be a valid HTTPS URL (https://…)'
  }

  const setVarMap = (variable: string, patch: { source?: string; value?: string }) =>
    setForm((f) => ({
      ...f,
      var_map: {
        ...f.var_map,
        [variable]: {
          source: patch.source ?? f.var_map[variable]?.source ?? 'name',
          value: patch.value ?? f.var_map[variable]?.value ?? '',
        },
      },
    }))

  const handleMediaFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setMediaError('')
    setMediaUploading(true)
    try {
      const uploaded = await operationsApi.uploadCampaignMedia(tenantId, file)
      set('media_filename', uploaded.filename)
    } catch (err) {
      setMediaError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setMediaUploading(false)
    }
  }

  const submit = () => {
    setTouched(true)
    if (!form.name.trim()) return
    if (!form.whatsapp_template) return
    if (form.audience_type === 'segments' && !form.segment_id) return
    if (form.schedule_mode === 'scheduled' && (!form.scheduled_date || !form.scheduled_time)) return
    if (!mediaValid) return
    if (!ctaValid) return

    const scheduledAt =
      form.schedule_mode === 'scheduled' && form.scheduled_date && form.scheduled_time
        ? `${form.scheduled_date}T${form.scheduled_time}:00`
        : null

    // Variable mapping: mapped fields store the {field} placeholder, fixed
    // values store the literal — the send-time resolver understands both.
    const templateVariableValues: Record<string, string> = {}
    for (const variable of templateVariables) {
      const mapping = form.var_map[variable] ?? { source: 'name', value: '' }
      templateVariableValues[variable] =
        mapping.source === 'fixed' ? mapping.value : `{${mapping.source}}`
    }

    const buttons: unknown[] =
      ctaText && ctaUrl ? [{ type: 'url', text: ctaText, url: ctaUrl }] : []

    onSubmit({
      name: form.name.trim(),
      status: initial ? form.status : 'scheduled',
      campaign_type: form.campaign_type,
      audience_type: form.audience_type,
      segment_id: form.audience_type === 'segments' ? form.segment_id : null,
      whatsapp_template: form.whatsapp_template,
      template_type: 'whatsapp_template',
      message_template: selectedTemplate?.body ?? '',
      template_variables: templateVariableValues,
      variable_fallbacks: form.var_fallbacks,
      buttons,
      media_filename: form.media_filename.trim() || null,
      schedule_mode: form.schedule_mode,
      scheduled_at: scheduledAt,
      timezone: form.timezone.trim() || 'Asia/Kolkata',
    })
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title={initial ? `Edit ${initial.name || `Campaign #${initial.id}`}` : 'New campaign'}
        description="The campaign will be sent to all contacts included in the selected audience when the schedule fires."
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Campaign Name *"
            value={form.name}
            error={nameMissing ? 'Campaign name is required' : undefined}
            onChange={(e) => set('name', e.target.value)}
            placeholder="Diwali Restock Offer"
          />
          <Select
            label="Campaign Type *"
            value={form.campaign_type}
            onChange={(e) => set('campaign_type', e.target.value)}
          >
            {CAMPAIGN_TYPES.map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </Select>
          <Select
            label="WhatsApp Template *"
            value={form.whatsapp_template}
            error={templateMissing ? 'An approved WhatsApp template is required' : undefined}
            onChange={(e) => set('whatsapp_template', e.target.value)}
            hint={
              approvedTemplates.length
                ? 'Select an approved template — its body becomes the message.'
                : 'No approved templates yet — add one via Manage templates.'
            }
          >
            <option value="">Select approved template</option>
            {approvedTemplates.map((template) => (
              <option key={template.id} value={template.name}>
                {template.name}
              </option>
            ))}
          </Select>
          {initial &&
            (ADMIN_STATUSES.includes(form.status as (typeof ADMIN_STATUSES)[number]) ? (
              <Select label="Status" value={form.status} onChange={(e) => set('status', e.target.value)}>
                {ADMIN_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </Select>
            ) : (
              <Input
                label="Status"
                value={form.status}
                disabled
                hint="Managed by the broadcast engine."
              />
            ))}
        </div>

        {/* Audience */}
        <div>
          <p className="field-label mb-1.5">Audience *</p>
          <div className="flex flex-wrap gap-4">
            {AUDIENCES.map((audience) => (
              <label key={audience.value} className="flex cursor-pointer items-center gap-1.5 text-sm text-slate-200">
                <input
                  type="radio"
                  name="campaign-audience"
                  className="accent-accent-500"
                  checked={form.audience_type === audience.value}
                  onChange={() => set('audience_type', audience.value)}
                />
                {audience.label}
              </label>
            ))}
          </div>
        </div>
        {form.audience_type === 'segments' && (
          <Select
            label="Select Segment *"
            value={form.segment_id ?? ''}
            error={segmentMissing ? 'A segment is required' : undefined}
            onChange={(e) => set('segment_id', e.target.value ? Number(e.target.value) : null)}
            hint={
              segments.length
                ? 'Each segment carries its own audience type and criteria.'
                : 'No segments yet — create one via Manage segments.'
            }
          >
            <option value="">Select segment</option>
            {segments.map((segment) => (
              <option key={segment.id} value={segment.id}>
                {segment.name} — {segment.audience_type === 'customers' ? 'Customer' : 'Distributor'} ·{' '}
                {segment.target_count} contacts
              </option>
            ))}
          </Select>
        )}

        {/* Message preview from the selected template */}
        <div>
          <p className="field-label mb-1.5">Message preview</p>
          {selectedTemplate ? (
            <div className="rounded-lg bg-surface p-4 text-sm leading-relaxed text-slate-200 ring-1 ring-inset ring-surface-line">
              <p className="whitespace-pre-wrap">{selectedTemplate.body}</p>
              <p className="mt-2 text-xs text-slate-500">
                Variables will be replaced automatically for each recipient.
              </p>
            </div>
          ) : (
            <p className="rounded-lg bg-surface-panel p-3 text-xs text-slate-500">
              Select an approved WhatsApp template to preview its message.
            </p>
          )}
        </div>

        {/* Template variables mapped per variable, not raw JSON */}
        {templateVariables.length > 0 && (
          <div className="space-y-2">
            <p className="field-label">Template Variables *</p>
            {templateVariables.map((variable) => {
              const mapping = form.var_map[variable] ?? { source: 'name', value: '' }
              return (
                <div key={variable} className="grid gap-2 sm:grid-cols-2">
                  <Input label={`{{${variable}}}`} value={`{{${variable}}}`} disabled />
                  <Select
                    label="Map to"
                    value={mapping.source}
                    onChange={(e) => setVarMap(variable, { source: e.target.value })}
                  >
                    {VAR_FIELD_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                  {mapping.source === 'fixed' && (
                    <Input
                      label="Fixed value"
                      value={mapping.value}
                      onChange={(e) => setVarMap(variable, { value: e.target.value })}
                      placeholder={`Value for {{${variable}}}`}
                    />
                  )}
                  <Input
                    label="Fallback (optional)"
                    value={form.var_fallbacks[variable] ?? ''}
                    onChange={(e) =>
                      setForm((f) => ({
                        ...f,
                        var_fallbacks: { ...f.var_fallbacks, [variable]: e.target.value },
                      }))
                    }
                    hint={`Used when the recipient has no ${variable}`}
                  />
                </div>
              )
            })}
          </div>
        )}

        {/* Schedule */}
        <div className="space-y-3">
          <div>
            <p className="field-label mb-1.5">Schedule Mode *</p>
            <div className="flex flex-wrap gap-4">
              {[
                { value: 'now', label: 'Send Now' },
                { value: 'scheduled', label: 'Schedule for Later' },
              ].map((mode) => (
                <label key={mode.value} className="flex cursor-pointer items-center gap-1.5 text-sm text-slate-200">
                  <input
                    type="radio"
                    name="campaign-schedule"
                    className="accent-accent-500"
                    checked={form.schedule_mode === mode.value}
                    onChange={() => set('schedule_mode', mode.value as 'now' | 'scheduled')}
                  />
                  {mode.label}
                </label>
              ))}
            </div>
          </div>
          {form.schedule_mode === 'scheduled' && (
            <div className="grid gap-4 sm:grid-cols-3">
              <Input
                label="Schedule Date *"
                type="date"
                value={form.scheduled_date}
                error={scheduleDateMissing ? 'Schedule date is required' : undefined}
                onChange={(e) => set('scheduled_date', e.target.value)}
              />
              <Input
                label="Schedule Time *"
                type="time"
                value={form.scheduled_time}
                error={scheduleTimeMissing ? 'Schedule time is required' : undefined}
                onChange={(e) => set('scheduled_time', e.target.value)}
              />
              <Select label="Timezone" value={form.timezone} onChange={(e) => set('timezone', e.target.value)}>
                {timezoneOptions(form.timezone).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </Select>
            </div>
          )}
        </div>

        {/* Media upload + CTA */}
        <div>
          <p className="field-label mb-1.5">Media (optional)</p>
          <div className="flex flex-wrap items-center gap-2">
            <label
              className={`inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-surface-panel px-3 py-2 text-sm text-slate-200 ring-1 ring-inset ring-surface-line transition hover:bg-surface ${
                mediaUploading ? 'pointer-events-none opacity-60' : ''
              }`}
            >
              <input
                type="file"
                className="hidden"
                accept=".jpg,.jpeg,.png,.mp4"
                disabled={mediaUploading}
                onChange={handleMediaFile}
              />
              {mediaUploading ? 'Uploading…' : 'Upload image / video'}
            </label>
            {form.media_filename && (
              <>
                <span className="max-w-full truncate rounded bg-surface-panel px-2 py-1 text-xs text-slate-300">
                  {form.media_filename}
                </span>
                <Button size="sm" variant="ghost" onClick={() => set('media_filename', '')}>
                  Remove
                </Button>
              </>
            )}
          </div>
          {mediaError && <p className="mt-1 text-xs text-rose-400">{mediaError}</p>}
          <p className="mt-1 text-xs text-slate-500">
            Supported: JPG, PNG, MP4 — up to 16 MB. The file uploads immediately and attaches to the campaign.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="CTA Button Text (optional)"
            value={form.cta_button_text}
            onChange={(e) => set('cta_button_text', e.target.value)}
            placeholder="Shop Now"
          />
          <Input
            label="CTA Button URL (optional)"
            value={form.cta_button_url}
            error={!ctaValid ? ctaError : undefined}
            onChange={(e) => set('cta_button_url', e.target.value)}
            placeholder="https://example.com"
          />
        </div>

        {initial && (
          <div className="grid gap-4 sm:grid-cols-2">
            <Input
              label="Send a test to"
              value={testWaId}
              onChange={(e) => setTestWaId(e.target.value)}
              placeholder="WhatsApp id, e.g. 919876543210"
              hint="Sends the rendered message (with fallbacks) to one number before the broadcast."
            />
            <div className="flex items-end">
              <Button
                variant="secondary"
                disabled={!testWaId.trim()}
                onClick={() => onTestSend(testWaId.trim())}
              >
                Send test
              </Button>
            </div>
          </div>
        )}

        {error && <Alert tone="danger" title="Could not save">{error}</Alert>}

        <div className="flex items-center gap-2">
          <Button variant="primary" loading={busy} onClick={submit}>
            {initial ? 'Save changes' : 'Create campaign'}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
