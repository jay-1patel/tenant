import { useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { type Campaign, type CampaignInput, operationsApi } from '@/lib/operations'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  draft: 'muted',
  scheduled: 'accent',
  sending: 'warning',
  sent: 'success',
  failed: 'danger',
  cancelled: 'danger',
}

/** Statuses an admin can set from the console; the rest are set by the scheduler. */
const CAMPAIGN_STATUSES = ['draft', 'scheduled', 'sent', 'cancelled']

interface CampaignFormShape {
  name: string
  status: string
  campaign_type: string
  whatsapp_template: string
  audience_type: string
  template_variables: string
  message_template: string
  schedule_mode: string
  scheduled_date: string
  scheduled_time: string
  timezone: string
  media_filename: string
  cta_button_text: string
  cta_button_url: string
}

function toShape(campaign?: Campaign | null): CampaignFormShape {
  let templateVars = ''
  try {
    if (campaign?.template_variables && Object.keys(campaign.template_variables).length > 0) {
      templateVars = JSON.stringify(campaign.template_variables, null, 2)
    }
  } catch {
    templateVars = ''
  }

  let scheduledDate = ''
  let scheduledTime = ''
  if (campaign?.scheduled_at) {
    const dt = new Date(campaign.scheduled_at)
    if (!Number.isNaN(dt.getTime())) {
      const year = dt.getFullYear()
      const month = String(dt.getMonth() + 1).padStart(2, '0')
      const day = String(dt.getDate()).padStart(2, '0')
      scheduledDate = `${year}-${month}-${day}`
      scheduledTime = dt.toTimeString().slice(0, 5)
    }
  }

  return {
    name: campaign?.name ?? '',
    status: campaign?.status ?? 'draft',
    campaign_type: campaign?.template_type ?? '',
    whatsapp_template: campaign?.template_type ?? '',
    audience_type: campaign?.audience_type ?? 'all',
    template_variables: templateVars,
    message_template: campaign?.message_template ?? '',
    schedule_mode: campaign?.schedule_mode ?? 'now',
    scheduled_date: scheduledDate,
    scheduled_time: scheduledTime,
    timezone: campaign?.timezone ?? 'Asia/Kolkata',
    media_filename: campaign?.media_filename ?? '',
    cta_button_text: '',
    cta_button_url: '',
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

  const state = useAsync((signal) => operationsApi.campaigns(tenantId, signal), [tenantId])

  const campaigns = state.data?.campaigns ?? []
  const stats = state.data?.stats

  const submit = async (input: Omit<CampaignInput, 'audience_type' | 'segment' | 'template_type' | 'template_variables' | 'buttons' | 'list_items' | 'media_filename'>) => {
    if (editing) {
      // PUT replaces every column, so pass the fields the form does not own
      // straight through from the stored campaign.
      const body: CampaignInput = {
        ...input,
        audience_type: editing.audience_type,
        segment: editing.segment ?? null,
        template_type: editing.template_type,
        template_variables: editing.template_variables ?? {},
        buttons: editing.buttons ?? [],
        list_items: editing.list_items ?? [],
        media_filename: editing.media_filename ?? null,
      }
      const result = await action.run(() => operationsApi.updateCampaign(tenantId, editing.id, body))
      if (result) {
        toast.push('Campaign updated')
        setEditing(null)
        state.reload()
      }
      return
    }
    const result = await action.run(() => operationsApi.createCampaign(tenantId, { ...input, audience_type: 'all' }))
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
          canManage && !creating && !editing && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              New campaign
            </Button>
          )
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

      {(creating || editing) && (
        <CampaignForm
          initial={editing}
          busy={action.busy}
          error={action.error}
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
            description="Create a broadcast here and it will be sent to the audience when its schedule fires."
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
          <CardBody className="divide-y divide-surface-line">
            {campaigns.map((campaign) => (
              <div key={campaign.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {campaign.name || `Campaign #${campaign.id}`}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {campaign.audience_type} · {campaign.target_count} targeted
                    {campaign.schedule_mode === 'scheduled' && campaign.scheduled_at
                      ? ` · scheduled ${formatDate(campaign.scheduled_at)}`
                      : ''}
                    {campaign.created_at ? ` · created ${formatDate(campaign.created_at)}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={STATUS_TONE[campaign.status] ?? 'neutral'}>{campaign.status}</Badge>
                  <Badge tone="muted">{campaign.metrics?.sent ?? 0} sent</Badge>
                  <Badge tone="accent">{campaign.metrics?.replied ?? 0} replied</Badge>
                  {(campaign.metrics?.failed ?? 0) > 0 && (
                    <Badge tone="danger">{campaign.metrics?.failed} failed</Badge>
                  )}
                  {canManage && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(campaign)}>
                        <Pencil className="h-3.5 w-3.5" /> Edit
                      </Button>
                      {confirmDelete === campaign.id ? (
                        <>
                          <Button
                            size="sm"
                            variant="danger"
                            loading={action.busy}
                            onClick={() => remove(campaign)}
                          >
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
                    </>
                  )}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function CampaignForm({
  initial,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  initial: Campaign | null
  busy: boolean
  error: string | null
  onSubmit: (input: {
    name: string
    status: string
    message_template: string
    schedule_mode: string
    scheduled_at?: string | null
    timezone?: string
  }) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<CampaignFormShape>(() => toShape(initial))
  const [touched, setTouched] = useState(false)

  const set = <K extends keyof CampaignFormShape>(key: K, value: CampaignFormShape[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const nameMissing = touched && !form.name.trim()
  const campaignTypeMissing = touched && !form.campaign_type.trim()
  const whatsappTemplateMissing = touched && !form.whatsapp_template.trim()
  const audienceMissing = touched && !form.audience_type.trim()
  const messageMissing = touched && !form.message_template.trim()
  const scheduleDateMissing = touched && form.schedule_mode === 'scheduled' && !form.scheduled_date.trim()
  const scheduleTimeMissing = touched && form.schedule_mode === 'scheduled' && !form.scheduled_time.trim()
  
  let templateVarsValid = true
  let templateVarsError = ''
  if (touched && form.template_variables.trim()) {
    try {
      const parsed = JSON.parse(form.template_variables)
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed) || Object.keys(parsed).length === 0) {
        templateVarsValid = false
        templateVarsError = 'Template variables must be a non-empty object (e.g. {"name":"value"})'
      }
    } catch {
      templateVarsValid = false
      templateVarsError = 'Template variables must be valid JSON'
    }
  } else if (touched && !form.template_variables.trim()) {
    templateVarsValid = false
    templateVarsError = 'Template variables are required'
  }

  let ctaValid = true
  let ctaError = ''
  if (form.cta_button_text.trim() || form.cta_button_url.trim()) {
    if (!form.cta_button_text.trim() || !form.cta_button_url.trim()) {
      ctaValid = false
      ctaError = 'Both CTA text and URL are required'
    } else if (!/^https?:\/\//i.test(form.cta_button_url.trim())) {
      ctaValid = false
      ctaError = 'CTA URL must be valid (http/https)'
    }
  }

  const submit = () => {
    setTouched(true)
    if (!form.name.trim()) return
    if (!form.campaign_type.trim()) return
    if (!form.whatsapp_template.trim()) return
    if (!form.audience_type.trim()) return
    if (!form.message_template.trim()) return
    if (!templateVarsValid) return
    if (form.schedule_mode === 'scheduled' && (!form.scheduled_date.trim() || !form.scheduled_time.trim())) return
    if (!ctaValid) return

    let scheduledAt: string | null = null
    if (form.schedule_mode === 'scheduled' && form.scheduled_date && form.scheduled_time) {
      scheduledAt = `${form.scheduled_date}T${form.scheduled_time}:00`
    }

    let templateVariablesParsed: Record<string, unknown> = {}
    if (form.template_variables.trim()) {
      try {
        templateVariablesParsed = JSON.parse(form.template_variables)
      } catch {
        templateVariablesParsed = {}
      }
    }

    const buttons: unknown[] = []
    if (form.cta_button_text.trim() && form.cta_button_url.trim()) {
      buttons.push({
        type: 'url',
        text: form.cta_button_text.trim(),
        url: form.cta_button_url.trim(),
      })
    }

    onSubmit({
      name: form.name.trim(),
      status: initial ? form.status : 'draft',
      message_template: form.message_template.trim(),
      schedule_mode: form.schedule_mode,
      scheduled_at: scheduledAt,
      timezone: form.timezone.trim() || 'Asia/Kolkata',
      audience_type: form.audience_type,
      template_type: form.whatsapp_template.trim() || form.campaign_type.trim(),
      template_variables: templateVariablesParsed,
      media_filename: form.media_filename.trim() || null,
      buttons,
    } as any)
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title={initial ? `Edit ${initial.name || `Campaign #${initial.id}`}` : 'New campaign'}
        description="The message body is broadcast to every distributor in the audience when the schedule fires."
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Campaign Name *"
            value={form.name}
            error={nameMissing ? 'Campaign name is required' : undefined}
            onChange={(e) => set('name', e.target.value)}
            placeholder="Diwali restock offer"
          />
          <Input
            label="Campaign Type *"
            value={form.campaign_type}
            error={campaignTypeMissing ? 'Campaign type is required' : undefined}
            onChange={(e) => set('campaign_type', e.target.value)}
            placeholder="promotional / transactional"
          />
          <Input
            label="WhatsApp Template *"
            value={form.whatsapp_template}
            error={whatsappTemplateMissing ? 'WhatsApp template is required' : undefined}
            onChange={(e) => set('whatsapp_template', e.target.value)}
            placeholder="template_name"
          />
          <Select
            label="Audience *"
            value={form.audience_type}
            error={audienceMissing ? 'Audience is required' : undefined}
            onChange={(e) => set('audience_type', e.target.value)}
          >
            <option value="">Select audience</option>
            <option value="all">All</option>
            <option value="distributors">Distributors</option>
            <option value="customers">Customers</option>
            <option value="segment">Segment</option>
          </Select>
          {initial && (
            <Select label="Status (auto-managed)" value={form.status} onChange={(e) => set('status', e.target.value)}>
              <option value="draft">draft</option>
              <option value="scheduled">scheduled</option>
              <option value="sent">sent</option>
              <option value="cancelled">cancelled</option>
            </Select>
          )}
        </div>

        <Textarea
          label="Message/Template Variables *"
          rows={4}
          value={form.template_variables}
          error={!templateVarsValid ? templateVarsError : undefined}
          onChange={(e) => set('template_variables', e.target.value)}
          hint="Enter template variables as JSON object (e.g. {&quot;name&quot;: &quot;{name}&quot;})"
          placeholder='{"name": "John"}'
        />

        <Textarea
          label="Message *"
          rows={4}
          value={form.message_template}
          error={messageMissing ? 'Message is required' : undefined}
          onChange={(e) => set('message_template', e.target.value)}
          hint="Sent as-is. Use *bold* WhatsApp formatting; variables like {name} resolve at send time."
        />

        <div className="grid gap-4 sm:grid-cols-4">
          <Select label="Schedule Mode" value={form.schedule_mode} onChange={(e) => set('schedule_mode', e.target.value)}>
            <option value="now">Now</option>
            <option value="scheduled">Scheduled</option>
          </Select>
          <Input
            label="Schedule Date *"
            type="date"
            value={form.scheduled_date}
            error={scheduleDateMissing ? 'Schedule date is required' : undefined}
            onChange={(e) => set('scheduled_date', e.target.value)}
            disabled={form.schedule_mode !== 'scheduled'}
          />
          <Input
            label="Schedule Time *"
            type="time"
            value={form.scheduled_time}
            error={scheduleTimeMissing ? 'Schedule time is required' : undefined}
            onChange={(e) => set('scheduled_time', e.target.value)}
            disabled={form.schedule_mode !== 'scheduled'}
          />
          <Input
            label="Timezone"
            value={form.timezone}
            onChange={(e) => set('timezone', e.target.value)}
            placeholder="Asia/Kolkata"
          />
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Media (optional)"
            value={form.media_filename}
            onChange={(e) => set('media_filename', e.target.value)}
            placeholder="image.jpg or video.mp4"
            hint="Media file name/path if attached"
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
