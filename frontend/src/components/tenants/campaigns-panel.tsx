import { useEffect, useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import {
  type Campaign,
  type CampaignInput,
  type CampaignSegmentOption,
  type CampaignTemplate,
  operationsApi,
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
const ADMIN_STATUSES = ['draft', 'scheduled', 'cancelled'] as const

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
  segment_id: string
  var_map: VarMap
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
    segment_id: '',
    var_map: varMap,
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

      {(creating || editing) && (
        <CampaignForm
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
  const [category, setCategory] = useState('promotional')
  const [body, setBody] = useState('')
  const [touched, setTouched] = useState(false)

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
      }),
    )
    if (result) {
      toast.push('Template added')
      setName('')
      setBody('')
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

  return (
    <Card className="mb-4">
      <CardHeader
        title="WhatsApp templates"
        description="Approved templates are what campaigns broadcast. Adding a template here registers it as approved."
      />
      <CardBody className="space-y-4">
        {templates.length > 0 ? (
          <div className="divide-y divide-surface-line rounded-lg ring-1 ring-inset ring-surface-line">
            {templates.map((template) => (
              <div key={template.id} className="flex flex-wrap items-start gap-3 px-4 py-2.5">
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-slate-100">
                    {template.name}{' '}
                    <span className="text-xs font-normal text-slate-500">({template.category})</span>
                  </p>
                  <p className="mt-0.5 whitespace-pre-wrap text-xs text-slate-400">{template.body}</p>
                </div>
                <div className="flex items-center gap-1.5">
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
          <Select label="Category" value={category} onChange={(e) => setCategory(e.target.value)}>
            {['MARKETING', 'UTILITY', 'AUTHENTICATION'].map((type) => (
              <option key={type} value={type}>
                {type}
              </option>
            ))}
          </Select>
        </div>
        <Textarea
          label="Template body *"
          rows={3}
          value={body}
          error={bodyMissing ? 'A template body is required' : undefined}
          onChange={(e) => setBody(e.target.value)}
          hint="Use {{name}} style placeholders; campaigns map them to each recipient's details."
          placeholder="Hi {{name}}, get 20% off on your Diwali restock."
        />
        <Button variant="primary" loading={action.busy} onClick={add}>
          Add template
        </Button>
        {action.error && <Alert tone="danger" title="Could not save template">{action.error}</Alert>}
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
  onSubmit,
  onCancel,
}: {
  initial: Campaign | null
  busy: boolean
  error: string | null
  templates: CampaignTemplate[]
  segments: CampaignSegmentOption[]
  onSubmit: (input: CampaignInput) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<CampaignFormShape>(() => toShape(initial))
  const [touched, setTouched] = useState(false)

  // When editing, re-attach the stored segment to its option once segments load.
  useEffect(() => {
    if (!initial?.segment || form.segment_id) return
    const match = segments.find(
      (s) => JSON.stringify(s.segment) === JSON.stringify(initial.segment),
    )
    if (match) setForm((f) => ({ ...f, segment_id: match.id }))
  }, [segments, initial, form.segment_id])

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
      segment:
        form.audience_type === 'segments'
          ? segments.find((s) => s.id === form.segment_id)?.segment ?? null
          : null,
      whatsapp_template: form.whatsapp_template,
      template_type: 'whatsapp_template',
      message_template: selectedTemplate?.body ?? '',
      template_variables: templateVariableValues,
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
            value={form.segment_id}
            error={segmentMissing ? 'A segment is required' : undefined}
            onChange={(e) => set('segment_id', e.target.value)}
          >
            <option value="">Select segment</option>
            {segments.map((segment) => (
              <option key={segment.id} value={segment.id}>
                {segment.label}
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

        {/* Media + CTA */}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Media (optional)"
            value={form.media_filename}
            error={!mediaValid ? 'Media must be a JPG, PNG or MP4 file' : undefined}
            onChange={(e) => set('media_filename', e.target.value)}
            placeholder="image.jpg or video.mp4"
            hint="Media file name/path if attached. Supported: JPG, PNG, MP4."
          />
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
