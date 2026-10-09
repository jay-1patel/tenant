import { useEffect, useMemo, useState } from 'react'
import { Check, Pencil, RotateCcw, Save, Send, TriangleAlert } from 'lucide-react'
import { useAction } from '@/lib/hooks'
import { tenantsApi } from '@/lib/tenants'
import { editorContactErrors, editorFromProfile, editorToSnapshot, timezoneOptions, type EditorForm } from '@/lib/profile'
import { getVertical } from '@/lib/verticals'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, SectionTitle } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tags'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useAuth } from '@/lib/auth'
import { useToast } from '@/components/ui/toast'
import { useTenantDetail } from '@/components/tenants/hooks'

export function ProfileEditor({ tenantId }: { tenantId: string }) {
  const detail = useTenantDetail(tenantId)
  const { identity } = useAuth()
  const isSuperAdmin = identity?.role === 'super_admin'
  const action = useAction()
  const toast = useToast()
  const [form, setForm] = useState<EditorForm | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [dirty, setDirty] = useState(false)
  // The profile is read-only until the admin explicitly opts in, so a stray
  // click on a switch or input cannot silently rewrite a live tenant.
  const [editing, setEditing] = useState(false)

  // Prefer the pending draft (merged over the file baseline): it contains
  // every unpublished change from the register wizard, so this editor and
  // the wizard always edit the same working copy.
  const effective = detail.data?.pending ?? detail.data?.effective ?? null
  const baseline = useMemo(
    () => (effective ? JSON.stringify(editorToSnapshot(editorFromProfile(effective))) : ''),
    [effective],
  )

  useEffect(() => {
    if (effective) {
      setForm(editorFromProfile(effective))
      setDirty(false)
    }
  }, [effective])

  if (detail.loading) return <LoadingBlock label="Loading the profile…" />
  if (detail.error) {
    return (
      <Alert tone="danger" title="Could not load the profile">
        {detail.error}
      </Alert>
    )
  }
  if (!form || !effective) {
    return (
      <Alert tone="warning" title="No effective profile">
        The merged profile could not be built for this tenant. Fix the failing layer, or publish a valid draft
        from the versions screen.
      </Alert>
    )
  }

  const vertical = getVertical(effective.vertical)
  const patch = (values: Partial<EditorForm>) => {
    if (!editing) return
    setForm((f) => (f ? { ...f, ...values } : f))
    setDirty(true)
  }
  const current = JSON.stringify(editorToSnapshot(form))

  const saveDraft = async (thenPublish: boolean) => {
    const contactErrors = editorContactErrors(form)
    if (contactErrors.length) {
      setWarnings(contactErrors)
      toast.push('Fix the contact details before saving.', 'error')
      return
    }
    const saved = await action.run(() => tenantsApi.saveDraft(tenantId, editorToSnapshot(form)))
    if (!saved) return
    setWarnings(saved.validation ?? [])
    setDirty(false)
    if (!thenPublish) {
      toast.push('Draft saved. Nothing is live until you publish.')
      detail.reload()
      return
    }
    if ((saved.validation ?? []).length) {
      toast.push('Draft has validation warnings — review them before publishing.', 'error')
      setWarnings(saved.validation)
      return
    }
    const published = await action.run(() => tenantsApi.publish(tenantId))
    if (published) {
      if (published.status === 'pending_approval') {
        toast.push(published.message ?? 'Change sent for super admin approval.')
      } else {
        toast.push(`Published version ${published.version}`)
      }
      setEditing(false)
      detail.reload()
    }
  }

  return (
    <div>
      <PageHeader
        title="Profile"
        description={
          isSuperAdmin
            ? "This form is the tenant's data layer. Saving writes a draft; publishing validates it, versions it and swaps the live profile. Publishing is the only thing the bot ever sees."
            : "This form is the tenant's data layer. Your edits are saved as a draft and submitted to a super admin — nothing goes live until they approve."
        }
        actions={
          editing ? (
            <>
              <Button
                size="sm"
                variant="ghost"
                icon={<RotateCcw className="h-4 w-4" />}
                disabled={!dirty}
                onClick={() => {
                  setForm(editorFromProfile(effective))
                  setDirty(false)
                  setWarnings([])
                }}
              >
                Discard changes
              </Button>
              {isSuperAdmin ? (
                <>
                  <Button
                    size="sm"
                    variant="secondary"
                    loading={action.busy}
                    icon={<Save className="h-4 w-4" />}
                    onClick={() => saveDraft(false)}
                  >
                    Save draft
                  </Button>
                  <Button
                    size="sm"
                    variant="primary"
                    loading={action.busy}
                    icon={<Send className="h-4 w-4" />}
                    onClick={() => saveDraft(true)}
                  >
                    Save & publish
                  </Button>
                </>
              ) : (
                <Button
                  size="sm"
                  variant="primary"
                  loading={action.busy}
                  icon={<Send className="h-4 w-4" />}
                  onClick={() => saveDraft(true)}
                >
                  Submit for approval
                </Button>
              )}
              <Button
                size="sm"
                variant="ghost"
                icon={<Check className="h-4 w-4" />}
                disabled={dirty}
                title={dirty ? 'Save or discard your changes first' : undefined}
                onClick={() => setEditing(false)}
              >
                Done editing
              </Button>
            </>
          ) : (
            <Button
              size="sm"
              variant="primary"
              icon={<Pencil className="h-4 w-4" />}
              onClick={() => setEditing(true)}
            >
              Edit profile
            </Button>
          )
        }
        meta={
          <>
            <span className={`text-xs ${dirty ? 'text-amber-700' : 'text-slate-500'}`}>
              {!editing
                ? 'Read-only — click Edit profile to make changes'
                : dirty
                  ? 'Unsaved changes'
                  : 'In sync with the live profile'}
            </span>
            <span className="text-xs text-slate-600">v{effective.vertical} · {vertical.label}</span>
          </>
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert tone="warning" title="Validation warnings" className="mb-4">
          <ul className="list-disc space-y-1 pl-4">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Brand" description="Names and contact details used in menus and signatures." />
          <CardBody className="space-y-4">
            <Input label="Display name" disabled={!editing} value={form.displayName} onChange={(e) => patch({ displayName: e.target.value })} />
            <Input label="Company name" disabled={!editing} value={form.brand.name} onChange={(e) => patch({ brand: { ...form.brand, name: e.target.value } })} />
            <Input label="Bot name" disabled={!editing} value={form.brand.botName} onChange={(e) => patch({ brand: { ...form.brand, botName: e.target.value } })} />
            <Input label="Tagline" disabled={!editing} value={form.brand.tagline} onChange={(e) => patch({ brand: { ...form.brand, tagline: e.target.value } })} />
            <Input label="Website" disabled={!editing} value={form.brand.website} onChange={(e) => patch({ brand: { ...form.brand, website: e.target.value } })} />
            <Input
              label="Support email"
              type="email"
              disabled={!editing}
              value={form.brand.supportEmail}
              onChange={(e) => patch({ brand: { ...form.brand, supportEmail: e.target.value } })}
            />
            <Input
              label="Support phone"
              disabled={!editing}
              value={form.brand.supportPhone}
              onChange={(e) => patch({ brand: { ...form.brand, supportPhone: e.target.value } })}
            />
            <Input
              label="Closing signature"
              disabled={!editing}
              value={form.brand.signature}
              onChange={(e) => patch({ brand: { ...form.brand, signature: e.target.value } })}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Vocabulary"
            description="The nouns the bot uses. Changing these changes every message, menu and prompt that uses them."
          />
          <CardBody className="space-y-4">
            {(
              [
                ['item_noun', 'Plural offering noun', 'products'],
                ['item_noun_singular', 'Singular offering noun', 'product'],
                ['browse_label', 'Browse label', 'Browse Products'],
                ['catalog_label', 'Brochure label', 'View Brochure'],
                ['lead_noun', 'Enquiry noun', 'enquiry'],
                ['enquiry_label', 'Enquiry button label', 'Enquire'],
                ['support_label', 'Support label', 'Support'],
              ] as const
            ).map(([key, label, example]) => (
              <Input
                key={key}
                label={label}
                disabled={!editing}
                value={form.vocabulary[key] ?? ''}
                placeholder={example}
                onChange={(e) => patch({ vocabulary: { ...form.vocabulary, [key]: e.target.value } })}
              />
            ))}
            <div>
              <SectionTitle hint="Comma separated. The classifier will not route anything to an intent that uses a term this profile switched off.">
                Domain keywords
              </SectionTitle>
              <TagInput
                disabled={!editing}
                value={form.keywords.split(',').map((s) => s.trim()).filter(Boolean)}
                onChange={(next) => patch({ keywords: next.join(', ') })}
              />
            </div>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Working hours" description="Outside these hours, flows swap to their out-of-hours variant." />
          <CardBody className="space-y-4">
            <Switch
              checked={form.businessHours.alwaysOpen}
              disabled={!editing}
              onChange={(alwaysOpen) => patch({ businessHours: { ...form.businessHours, alwaysOpen } })}
              label="Always open"
            />
            <div className="grid grid-cols-3 gap-3">
              <Select
                label="Timezone"
                disabled={!editing}
                value={form.businessHours.timezone}
                onChange={(e) => patch({ businessHours: { ...form.businessHours, timezone: e.target.value } })}
              >
                <option value="">Select…</option>
                {timezoneOptions(form.businessHours.timezone).map((tz) => (
                  <option key={tz} value={tz}>
                    {tz}
                  </option>
                ))}
              </Select>
              <Input
                label="Opens"
                type="time"
                disabled={!editing || form.businessHours.alwaysOpen}
                value={form.businessHours.open}
                onChange={(e) => patch({ businessHours: { ...form.businessHours, open: e.target.value } })}
              />
              <Input
                label="Closes"
                type="time"
                disabled={!editing || form.businessHours.alwaysOpen}
                value={form.businessHours.close}
                onChange={(e) => patch({ businessHours: { ...form.businessHours, close: e.target.value } })}
              />
            </div>
            <Textarea
              label="Out-of-hours message"
              rows={2}
              disabled={!editing}
              value={form.businessHours.outOfHoursMessage}
              onChange={(e) => patch({ businessHours: { ...form.businessHours, outOfHoursMessage: e.target.value } })}
            />
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Notifications" description="Where leads, quotes and handoffs are pushed." />
          <CardBody className="space-y-4">
            <Input
              label="Sales email"
              type="email"
              disabled={!editing}
              value={form.notifications.salesEmail}
              onChange={(e) => patch({ notifications: { ...form.notifications, salesEmail: e.target.value } })}
            />
            <Input
              label="Support email"
              type="email"
              disabled={!editing}
              value={form.notifications.supportEmail}
              onChange={(e) => patch({ notifications: { ...form.notifications, supportEmail: e.target.value } })}
            />
          </CardBody>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Guardrails" description="What the bot must never claim, and when it must stop and call a human." />
        <CardBody className="space-y-4">
          <Textarea
            label="Never state (one per line)"
            rows={4}
            disabled={!editing}
            value={form.guardrails.neverState}
            onChange={(e) => patch({ guardrails: { ...form.guardrails, neverState: e.target.value } })}
          />
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <p className="field-label">Forbidden terms</p>
              <TagInput
                disabled={!editing}
                value={split(form.guardrails.forbiddenTerms)}
                onChange={(next) => patch({ guardrails: { ...form.guardrails, forbiddenTerms: next.join(', ') } })}
              />
            </div>
            <div>
              <p className="field-label">Handoff keywords</p>
              <TagInput
                disabled={!editing}
                value={split(form.guardrails.handoffKeywords)}
                onChange={(next) => patch({ guardrails: { ...form.guardrails, handoffKeywords: next.join(', ') } })}
              />
            </div>
          </div>
          <div>
            <p className="field-label">Escalate on</p>
            <TagInput
              disabled={!editing}
              value={split(form.guardrails.escalateKeywords)}
              onChange={(next) => patch({ guardrails: { ...form.guardrails, escalateKeywords: next.join(', ') } })}
            />
          </div>
          <Input
            label="Escalation message"
            disabled={!editing}
            value={form.guardrails.escalationMessage}
            onChange={(e) => patch({ guardrails: { ...form.guardrails, escalationMessage: e.target.value } })}
          />
        </CardBody>
      </Card>

      <p className="mt-4 flex items-center gap-2 text-xs text-slate-600">
        <TriangleAlert className="h-3.5 w-3.5" />
        {current === baseline
          ? 'No changes yet.'
          : isSuperAdmin
            ? 'Unsaved changes will be written as a draft, not published.'
            : 'Unsaved changes stay a draft until you submit them for approval.'}
      </p>
    </div>
  )
}

function split(value: string): string[] {
  return value
    .split(/[,\n]/)
    .map((s) => s.trim())
    .filter(Boolean)
}
