import { useMemo, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  BadgeCheck,
  Building2,
  CalendarClock,
  Check,
  MessageSquareText,
  Rocket,
  ShieldAlert,
  Sparkles,
  Webhook,
} from 'lucide-react'
<<<<<<< HEAD
import { applyVertical, draftFromProfile, draftToSnapshot, emptyDraft, slugify, type WizardDraft } from '@/lib/profile'
=======
import { applyVertical, draftFromProfile, draftToSnapshot, emptyDraft, slugify, timezoneOptions, type WizardDraft } from '@/lib/profile'
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
import { useAction } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { tenantsApi, useTenants } from '@/lib/tenants'
import { tenantApprovalsApi } from '@/lib/tenant-approvals'
import { navigate } from '@/lib/router'
<<<<<<< HEAD
import { FEATURE_GROUPS, FEATURE_LABELS, VERTICAL_CATALOG, getVertical } from '@/lib/verticals'
import type { FeatureFlag, Tenant } from '@/lib/types'
=======
import { VERTICAL_CATALOG, getVertical } from '@/lib/verticals'
import type { Tenant } from '@/lib/types'
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader, SectionTitle } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tags'
import { Alert } from '@/components/ui/feedback'
import { VerticalGlyph } from '@/components/vertical-icon'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const DAYS = [
  { value: 1, label: 'Mon' },
  { value: 2, label: 'Tue' },
  { value: 3, label: 'Wed' },
  { value: 4, label: 'Thu' },
  { value: 5, label: 'Fri' },
  { value: 6, label: 'Sat' },
  { value: 0, label: 'Sun' },
]

/** Dropdown for the working-hours timezone — free text invited typos. */
<<<<<<< HEAD
const TIMEZONES = [
  'Asia/Kolkata',
  'Asia/Dubai',
  'Asia/Singapore',
  'Asia/Hong_Kong',
  'Asia/Tokyo',
  'Asia/Karachi',
  'Asia/Dhaka',
  'Europe/London',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Moscow',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Sao_Paulo',
  'Australia/Sydney',
  'Africa/Cairo',
  'Africa/Johannesburg',
  'UTC',
]
=======
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
// Country code (+91…) followed by a 10-digit number, spaces/dashes allowed.
const normalizePhone = (value: string) => value.replace(/[\s\-()]/g, "")

// Country calling codes. The subscriber part must be exactly 10 digits, so
// "+91 741852544" (9 digits) is rejected while "+91 98765 43210" passes.
const COUNTRY_CODES = [
  '1', '7', '20', '27', '30', '31', '32', '33', '34', '36', '39', '40', '41', '43', '44', '45', '46', '47', '48', '49',
  '51', '52', '53', '54', '55', '56', '57', '58', '60', '61', '62', '63', '64', '65', '66', '81', '82', '84', '86',
  '90', '91', '92', '93', '94', '95', '98',
  '212', '213', '216', '218', '220', '221', '222', '223', '224', '225', '226', '227', '228', '229', '230', '231',
  '232', '233', '234', '235', '236', '237', '238', '239', '240', '241', '242', '243', '244', '245', '246', '248',
  '249', '250', '251', '252', '253', '254', '255', '256', '257', '258', '260', '261', '262', '263', '264', '265',
  '266', '267', '268', '269', '290', '291', '297', '298', '299', '350', '351', '352', '353', '354', '355', '356',
  '357', '358', '359', '370', '371', '372', '373', '374', '375', '376', '377', '378', '380', '381', '382', '383',
  '385', '386', '387', '389', '420', '421', '423', '500', '501', '502', '503', '504', '505', '506', '507', '508',
  '509', '590', '591', '592', '593', '594', '595', '596', '597', '598', '599', '670', '672', '673', '674', '675',
  '676', '677', '678', '679', '680', '681', '682', '683', '685', '686', '687', '688', '689', '690', '691', '692',
  '850', '852', '853', '855', '856', '870', '880', '886', '960', '961', '962', '963', '964', '965', '966', '967',
  '968', '970', '971', '972', '973', '974', '975', '976', '977', '992', '993', '994', '995', '996', '998',
].sort((a, b) => b.length - a.length)

const isValidPhone = (raw: string) => {
  const digits = normalizePhone(raw)
  if (!/^\+\d{9,15}$/.test(digits)) return false
  const body = digits.slice(1)
  const cc = COUNTRY_CODES.find((code) => body.startsWith(code))
  if (!cc) return false
  return /^\d{10}$/.test(body.slice(cc.length))
}
const WABA_ID_RE = /^\d{6,25}$/

// The super admin only registers the company basics; an admin completes the
// tenant from WhatsApp onwards, and that completion goes for approval.
const SUPER_STEPS = [{ id: 'company', label: 'Company' }] as const

const ADMIN_STEPS = [
  { id: 'tenant', label: 'Tenant' },
  { id: 'whatsapp', label: 'WhatsApp' },
  { id: 'brand', label: 'Brand & voice' },
  { id: 'domain', label: 'Your business' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'guardrails', label: 'Guardrails' },
  { id: 'review', label: 'Review' },
] as const

type StepId = (typeof SUPER_STEPS | typeof ADMIN_STEPS)[number]['id']

export function RegisterWizard() {
  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<WizardDraft>(emptyDraft)
  const { reload, tenants } = useTenants()
  const { identity } = useAuth()
  const action = useAction()
  const toast = useToast()

  const isSuperAdmin = identity?.role === 'super_admin'
  const steps = isSuperAdmin ? SUPER_STEPS : ADMIN_STEPS
  const stepId = steps[step].id as StepId

  const patch = (values: Partial<WizardDraft>) => setDraft((d) => ({ ...d, ...values }))

  const tenantIdTaken = tenants.some((t) => t.id === draft.tenantId.trim())
  const error = useMemo(
    () => validationError(stepId, draft, tenantIdTaken, Boolean(draft.tenantId.trim())),
    [stepId, draft, tenantIdTaken],
  )

  /** Load the selected tenant's resolved profile into the wizard draft. */
  const pickTenant = async (tenantId: string) => {
    const tenant = tenants.find((t) => t.id === tenantId)
    if (!tenant) return
    const profile = await action.run(() => tenantsApi.resolved(tenantId))
    if (profile) {
      setDraft(draftFromProfile(profile, tenant))
    } else {
      // A tenant the resolver cannot build yet still keeps its basics.
      setDraft({ ...emptyDraft(), companyName: tenant.display_name || tenant.id, tenantId: tenant.id, displayName: tenant.display_name, vertical: tenant.vertical })
    }
  }

  const submit = async () => {
    if (isSuperAdmin) {
      // The super admin registers the company only. No publish: an admin
      // completes the tenant, and that completion needs approval.
      const created = await action.run(() =>
        tenantsApi.create({
          tenant_id: draft.tenantId.trim(),
          slug: draft.tenantId.trim(),
          vertical: draft.vertical,
          display_name: draft.displayName || draft.companyName,
          status: 'active',
        }),
      )
      if (!created) return

      const id = created.tenant.id
      const saved = await action.run(() => tenantsApi.saveDraft(id, draftToSnapshot(draft)))
      if (!saved) return

      toast.push(`${draft.companyName} registered. An admin can now complete it from WhatsApp onwards.`)
      reload()
      navigate(`/tenants/${encodeURIComponent(id)}/overview`)
      return
    }

    // Admin: bind the WhatsApp number, save the completed data as the
    // tenant's draft, then queue the publish for super admin approval.
    const id = draft.tenantId.trim()
    if (draft.wabaPhoneId.trim()) {
      const bound = await action.run(() => tenantsApi.bindPhone(id, draft.wabaPhoneId.trim()))
      if (!bound) return
    }
    const saved = await action.run(() => tenantsApi.saveDraft(id, draftToSnapshot(draft)))
    if (!saved) return
    if ((saved.validation ?? []).length) {
      toast.push('Draft has validation warnings — review them before submitting.', 'error')
      return
    }
    const submitted = await action.run(() => tenantApprovalsApi.submitPublish(id))
    if (!submitted) return
    toast.push(`${draft.companyName} submitted — a super admin must approve it before it goes live.`)
    reload()
    navigate('/tenant-requests')
  }

  return (
    <div className="mx-auto max-w-3xl">
      <PageHeader
        title="Register a tenant"
        description={
          isSuperAdmin
            ? 'Register the company basics — name, id and business field. An admin then completes the tenant from WhatsApp onwards, and their submission goes for your approval before anything goes live.'
            : 'Pick a tenant the super admin registered, then complete it from WhatsApp onwards. Your submission goes to a super admin for approval before anything goes live.'
        }
      />

      <ol className="mb-7 flex flex-wrap gap-1.5">
        {steps.map((s, index) => {
          const state = index === step ? 'current' : index < step ? 'done' : 'todo'
          return (
            <li key={s.id} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => index < step && setStep(index)}
                disabled={index > step}
                className={`flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition ${
                  state === 'current'
                    ? 'bg-accent-100 text-accent-800 ring-1 ring-inset ring-accent-300'
                    : state === 'done'
                      ? 'text-emerald-700 hover:text-emerald-700'
                      : 'text-slate-600'
                }`}
              >
                {state === 'done' ? <Check className="h-3 w-3" /> : <span>{index + 1}</span>}
                {s.label}
              </button>
              {index < steps.length - 1 && <span className="text-slate-600">/</span>}
            </li>
          )
        })}
      </ol>

      <Card>
        {stepId === 'tenant' && <TenantStep draft={draft} tenants={tenants} onPick={pickTenant} />}
        {stepId === 'company' && <CompanyStep draft={draft} patch={patch} />}
        {stepId === 'whatsapp' && <WhatsAppStep draft={draft} patch={patch} />}
        {stepId === 'brand' && <BrandStep draft={draft} patch={patch} />}
<<<<<<< HEAD
        {stepId === 'capabilities' && <CapabilitiesStep draft={draft} patch={patch} />}
=======
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
        {stepId === 'domain' && <DomainStep draft={draft} patch={patch} />}
        {stepId === 'notifications' && <NotificationsStep draft={draft} patch={patch} />}
        {stepId === 'guardrails' && <GuardrailsStep draft={draft} patch={patch} />}
        {stepId === 'review' && (
          <ReviewStep
            draft={draft}
            onEdit={setStep}
            approvalMode={!isSuperAdmin}
            companyEditable={isSuperAdmin}
          />
        )}

        {action.error && (
          <div className="px-5 pb-4">
            <Alert tone="danger" title="Registration failed">
              {action.error}
            </Alert>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-surface-line px-5 py-4">
          <Button
            variant="ghost"
            disabled={step === 0}
            onClick={() => setStep((s) => Math.max(0, s - 1))}
            icon={<ArrowLeft className="h-4 w-4" />}
          >
            Back
          </Button>

          {step < steps.length - 1 ? (
            <Button
              variant="primary"
              disabled={Boolean(error)}
              onClick={() => setStep((s) => s + 1)}
            >
              Continue
              <ArrowRight className="h-4 w-4" />
            </Button>
          ) : (
            <Button
              variant="primary"
              loading={action.busy}
              onClick={submit}
              icon={<Rocket className="h-4 w-4" />}
            >
              {isSuperAdmin ? 'Create tenant' : 'Submit for approval'}
            </Button>
          )}
        </div>
      </Card>

      {error && step < steps.length - 1 && (
        <p className="mt-3 text-xs text-amber-700/80">{error}</p>
      )}
      {isSuperAdmin && tenantIdTaken && stepId === 'company' && (
        <Alert tone="warning" className="mt-4">
          A tenant with this id already exists. Pick another id, or cancel and edit the existing tenant instead.
        </Alert>
      )}
    </div>
  )
}

// ── steps ──────────────────────────────────────────────────────────────────

/**
 * Admin-only first step: pick one of the tenants the super admin registered.
 * The company basics were entered by the super admin and are read-only here.
 */
function TenantStep({
  draft,
  tenants,
  onPick,
}: {
  draft: WizardDraft
  tenants: Tenant[]
  onPick: (tenantId: string) => void
}) {
  return (
    <StepShell
      title="Which tenant are you completing?"
      description="The super admin registered the company basics. Pick the tenant, then complete it from WhatsApp onwards — your data goes to a super admin for approval."
      icon={<Building2 className="h-4 w-4" />}
    >
      <div className="space-y-2.5">
        {tenants.length === 0 && (
          <p className="text-sm text-slate-400">
            No tenants yet. A super admin registers the company first from this same panel.
          </p>
        )}
        {tenants.map((tenant) => {
          const vertical = getVertical(tenant.vertical)
          const active = draft.tenantId === tenant.id
          return (
            <button
              key={tenant.id}
              type="button"
              onClick={() => onPick(tenant.id)}
              className={`flex w-full items-center gap-3 rounded-lg p-3.5 text-left ring-1 ring-inset transition ${
                active ? 'bg-accent-100 ring-accent-400' : 'bg-surface-panel ring-surface-line hover:bg-accent-50'
              }`}
            >
              <VerticalGlyph
                name={vertical.icon}
                className={`h-5 w-5 shrink-0 ${active ? 'text-accent-700' : 'text-slate-500'}`}
              />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium text-slate-100">
                  {tenant.display_name || tenant.id}
                </span>
                <span className="mt-0.5 block font-mono text-xs text-slate-500">
                  {tenant.id} · {vertical.short}
                </span>
              </span>
              <Badge tone={tenant.current_version ? 'success' : 'warning'}>
                {tenant.current_version ? `live v${tenant.current_version}` : 'awaiting completion'}
              </Badge>
            </button>
          )
        })}
      </div>
    </StepShell>
  )
}

function StepShell({
  title,
  description,
  icon,
  children,
}: {
  title: string
  description: string
  icon: React.ReactNode
  children: React.ReactNode
}) {
  return (
    <>
      <CardHeader title={title} description={description} icon={icon} />
      <CardBody className="space-y-5">{children}</CardBody>
    </>
  )
}

function CompanyStep({ draft, patch }: StepProps) {
  return (
    <StepShell
      title="Who is this tenant?"
      description="The company and the business field decide everything that follows: which questions you are asked, which features are offered, and the words the bot uses."
      icon={<Building2 className="h-4 w-4" />}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
          label="Company name"
          value={draft.companyName}
          onChange={(e) => patch({ companyName: e.target.value, tenantId: draft.tenantId || slugify(e.target.value) })}
          placeholder="Leeway Softech"
          required
        />
        <Input
          label="Tenant id"
          value={draft.tenantId}
          onChange={(e) => patch({ tenantId: slugify(e.target.value) })}
          hint="Lowercase, no spaces. This is the id used in the API and the database."
          required
        />
        <Input
          label="Display name"
          value={draft.displayName}
          onChange={(e) => patch({ displayName: e.target.value })}
          placeholder={draft.companyName || 'Shown in menus'}
        />
        <Input
          label="Website"
          value={draft.website}
          onChange={(e) => patch({ website: e.target.value })}
          placeholder="https://example.com"
        />
      </div>

      <div>
        <SectionTitle hint="This is the single most important answer: it selects the profile defaults, the vocabulary, the menu and the intents.">
          Business field
        </SectionTitle>
        <div className="grid gap-2.5 sm:grid-cols-2">
          {VERTICAL_CATALOG.map((v) => {
            const active = draft.vertical === v.id
            return (
              <button
                key={v.id}
                type="button"
                onClick={() => patch(applyVertical(draft, v.id))}
                className={`flex gap-3 rounded-lg p-3.5 text-left ring-1 ring-inset transition ${
                  active
                    ? 'bg-accent-100 ring-accent-400'
                    : 'bg-surface-panel ring-surface-line hover:bg-accent-50'
                }`}
              >
                <VerticalGlyph
                  name={v.icon}
                  className={`mt-0.5 h-5 w-5 shrink-0 ${active ? 'text-accent-700' : 'text-slate-500'}`}
                />
                <span className="min-w-0">
                  <span className="block text-sm font-medium text-slate-100">{v.label}</span>
                  <span className="mt-1 block text-xs leading-relaxed text-slate-400">{v.blurb}</span>
                </span>
              </button>
            )
          })}
        </div>
      </div>
    </StepShell>
  )
}

function WhatsAppStep({ draft, patch }: StepProps) {
  const toggleDay = (day: number) =>
    patch({
      openDays: draft.openDays.includes(day)
        ? draft.openDays.filter((d) => d !== day)
        : [...draft.openDays, day].sort(),
    })

  return (
    <StepShell
      title="WhatsApp and working hours"
      description="The phone number routes inbound messages to this tenant. Working hours decide when the bot offers a callback instead of a live handoff."
      icon={<CalendarClock className="h-4 w-4" />}
    >
      <Input
        label="WhatsApp phone number id *"
        value={draft.wabaPhoneId}
        onChange={(e) => patch({ wabaPhoneId: e.target.value })}
        placeholder="100012345678901"
        inputMode="numeric"
        hint="Digits only, from the Meta Business account (WABA). Each number belongs to exactly one tenant."
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <Select
          label="Timezone *"
          value={draft.timezone}
          onChange={(e) => patch({ timezone: e.target.value })}
          hint="Used by out-of-hours and callback logic."
        >
          <option value="">Select…</option>
<<<<<<< HEAD
          {(TIMEZONES.includes(draft.timezone) || !draft.timezone ? TIMEZONES : [draft.timezone, ...TIMEZONES]).map((tz) => (
=======
          {timezoneOptions(draft.timezone).map((tz) => (
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </Select>
        <Input
          label="Opens"
          type="time"
          value={draft.openTime}
          onChange={(e) => patch({ openTime: e.target.value })}
          disabled={draft.alwaysOpen}
        />
        <Input
          label="Closes"
          type="time"
          value={draft.closeTime}
          onChange={(e) => patch({ closeTime: e.target.value })}
          disabled={draft.alwaysOpen}
        />
      </div>

      <Switch
        checked={draft.alwaysOpen}
        onChange={(alwaysOpen) => patch({ alwaysOpen })}
        label="Always open"
        description="When off, out-of-hours conversations get a callback flow instead of a handoff."
      />

      {!draft.alwaysOpen && (
        <div className="space-y-3">
          <div>
            <p className="field-label">Open on</p>
            <div className="flex flex-wrap gap-1.5">
              {DAYS.map((day) => {
                const on = draft.openDays.includes(day.value)
                return (
                  <button
                    key={day.value}
                    type="button"
                    onClick={() => toggleDay(day.value)}
                    className={`h-9 w-12 rounded-lg text-xs font-medium ring-1 ring-inset transition ${
                      on
                        ? 'bg-accent-600 text-white ring-accent-500'
                        : 'bg-surface-raised text-slate-400 ring-surface-line hover:text-slate-100'
                    }`}
                  >
                    {day.label}
                  </button>
                )
              })}
            </div>
          </div>
          <Textarea
            label="Out-of-hours message"
            value={draft.outOfHoursMessage}
            onChange={(e) => patch({ outOfHoursMessage: e.target.value })}
          />
        </div>
      )}
    </StepShell>
  )
}

function BrandStep({ draft, patch }: StepProps) {
  const v = getVertical(draft.vertical)
  return (
    <StepShell
      title="Brand and voice"
      description="How the bot introduces itself and how it talks. These strings are used verbatim in menus and prompts."
      icon={<MessageSquareText className="h-4 w-4" />}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
        label="Bot name *"
          value={draft.botName}
          onChange={(e) => patch({ botName: e.target.value })}
          placeholder="Asha"
        />
        <Select
          label="Tone"
          value={draft.tone}
          onChange={(e) => patch({ tone: e.target.value })}
          hint={`${v.short} default: ${v.tone}`}
        >
          <option value="friendly and helpful">Friendly and helpful</option>
          <option value="professional and confident">Professional and confident</option>
          <option value="formal and compliant">Formal and compliant</option>
          <option value="warm and helpful">Warm and helpful</option>
          <option value="calm and empathetic">Calm and empathetic</option>
          <option value="concise and direct">Concise and direct</option>
        </Select>
        <Input
          label="Tagline"
          value={draft.tagline}
          onChange={(e) => patch({ tagline: e.target.value })}
          placeholder="Software that ships"
        />
        <Input
          label="Closing signature"
          value={draft.signature}
          onChange={(e) => patch({ signature: e.target.value })}
          placeholder="— Team Leeway"
        />
        <Input
          label="Support email *"
          type="email"
          value={draft.supportEmail}
          onChange={(e) => patch({ supportEmail: e.target.value })}
          placeholder="support@example.com"
        />
        <Input
          label="Support phone *"
          value={draft.supportPhone}
          onChange={(e) => patch({ supportPhone: e.target.value })}
          placeholder="+91 98765 43210"
          inputMode="tel"
          hint="Country code followed by a 10-digit number, e.g. +91 98765 43210."
        />
      </div>

      <Textarea
        label="Menu greeting"
        value={draft.greeting}
        onChange={(e) => patch({ greeting: e.target.value })}
        placeholder={`Hi! I'm ${draft.botName || 'the assistant'} from ${draft.companyName || 'our team'}. How can I help?`}
        hint="Shown as the WhatsApp menu body. Leave blank to use the field default."
      />

      <Alert tone="info" title={`Vocabulary for ${v.short}`}>
        The bot will call your offerings <strong>{v.nouns.item}</strong> and your enquiries{' '}
        <strong>{v.nouns.lead}</strong>. You can override every one of these later in the profile editor.
      </Alert>
    </StepShell>
  )
}

<<<<<<< HEAD
function CapabilitiesStep({ draft, patch }: StepProps) {
  const v = getVertical(draft.vertical)
  const on = new Set(draft.features)
  const toggle = (flag: FeatureFlag, next: boolean) =>
    patch({
      features: next ? [...draft.features, flag] : draft.features.filter((f) => f !== flag),
    })

  return (
    <StepShell
      title="What should the bot be able to do?"
      description={`For ${draft.displayName || draft.companyName || "this tenant"} (${v.short}). The switches start from what the field recommends${draft.tenantId ? " — or what the tenant already uses" : ""}; menus, intents and services all follow these flags.`}
      icon={<Sparkles className="h-4 w-4" />}
    >
      <div className="rounded-lg bg-accent-50 p-4 ring-1 ring-inset ring-accent-200">
        <p className="text-xs font-medium text-accent-700">With these capabilities your bot will:</p>
        <ul className="mt-2 space-y-1.5">
          {v.capabilities.map((line) => (
            <li key={line} className="flex gap-2 text-xs leading-relaxed text-slate-300">
              <Check className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-400" />
              {line}
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-5">
        {FEATURE_GROUPS.filter((g) => !v.hiddenGroups.includes(g.id)).map((group) => (
          <div key={group.id}>
            <SectionTitle hint={group.description}>{group.label}</SectionTitle>
            <div className="grid gap-2 sm:grid-cols-2">
              {group.flags.filter((flag) => flag !== 'handoff').map((flag) => {
                const meta = FEATURE_LABELS[flag]
                return (
                  <div key={flag} className="rounded-lg bg-surface-panel p-3 ring-1 ring-inset ring-surface-line">
                    <Switch
                      checked={on.has(flag)}
                      onChange={(next) => toggle(flag, next)}
                      label={meta.label}
                      description={meta.help}
                      size="sm"
                    />
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </StepShell>
  )
}

=======
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
function DomainStep({ draft, patch }: StepProps) {
  const v = getVertical(draft.vertical)
  const missingRequired = v.questions.filter((q) => q.required && !answerValue(draft, q.key))

  return (
    <StepShell
      title={`About your ${v.short.toLowerCase()} business`}
      description="These answers become the words the bot recognises. The more specific you are, the fewer questions it gets wrong."
      icon={<Sparkles className="h-4 w-4" />}
    >
      <div className="space-y-5">
        {v.questions.map((q) => {
          const value = draft.answers[q.key]
          return (
            <div key={q.key}>
              <p className="field-label">
                {q.label}
                {q.required && <span className="ml-1 text-rose-400">*</span>}
              </p>
              {q.kind === 'chips' && (
                <TagInput
                  value={Array.isArray(value) ? value : []}
                  onChange={(next) => patch({ answers: { ...draft.answers, [q.key]: next } })}
                  suggestions={q.suggestions ?? []}
                />
              )}
              {q.kind === 'text' && (
                <Input
                  value={typeof value === 'string' ? value : ''}
                  onChange={(e) => patch({ answers: { ...draft.answers, [q.key]: e.target.value } })}
                  placeholder={q.placeholder}
                />
              )}
              {q.kind === 'textarea' && (
                <Textarea
                  value={typeof value === 'string' ? value : ''}
                  onChange={(e) => patch({ answers: { ...draft.answers, [q.key]: e.target.value } })}
                  placeholder={q.placeholder}
                />
              )}
              {q.kind === 'select' && (
                <Select
                  value={typeof value === 'string' ? value : ''}
                  onChange={(e) => patch({ answers: { ...draft.answers, [q.key]: e.target.value } })}
                >
                  <option value="">Select…</option>
                  {(q.options ?? []).map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </Select>
              )}
              {q.help && <p className="hint">{q.help}</p>}
            </div>
          )
        })}
      </div>

      {missingRequired.length > 0 && (
        <Alert tone="warning">
          Answer {missingRequired.map((q) => q.label).join(', ')} before continuing.
        </Alert>
      )}
    </StepShell>
  )
}

function NotificationsStep({ draft, patch }: StepProps) {
  return (
    <StepShell
      title="Where do enquiries go?"
      description="Leads, quotes and handoffs are pushed to these destinations. A tenant with no destination configured will collect leads that nobody reads."
      icon={<Webhook className="h-4 w-4" />}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Input
          label="Sales / enquiries email *"
          type="email"
          value={draft.salesEmail}
          onChange={(e) => patch({ salesEmail: e.target.value })}
          placeholder="sales@example.com"
        />
        <Input
          label="Support email"
          type="email"
          value={draft.notificationsSupportEmail}
          onChange={(e) => patch({ notificationsSupportEmail: e.target.value })}
          placeholder="support@example.com"
        />
      </div>


    </StepShell>
  )
}

function GuardrailsStep({ draft, patch }: StepProps) {
  return (
    <StepShell
      title="What must the bot never do?"
      description="Guardrails bind the language model. Statements listed here are refused, and the escalation keywords hand the conversation to a person."
      icon={<ShieldAlert className="h-4 w-4" />}
    >
      <Textarea
        label="Never state (one per line)"
        value={draft.neverState}
        onChange={(e) => patch({ neverState: e.target.value })}
        placeholder={'We guarantee delivery in 24 hours\nOur stock is always in sync\nNo hidden charges, ever'}
        hint="The bot must not claim these. Empty means the vertical default applies."
      />
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <p className="field-label">Forbidden terms</p>
          <TagInput
            value={draft.forbiddenTerms}
            onChange={(forbiddenTerms) => patch({ forbiddenTerms })}
            placeholder="Terms to refuse"
          />
        </div>
        <div>
          <p className="field-label">Handoff keywords</p>
          <TagInput
            value={draft.handoffKeywords}
            onChange={(handoffKeywords) => patch({ handoffKeywords })}
            placeholder="human, agent…"
          />
        </div>
      </div>
      <div>
        <p className="field-label">Escalate immediately on</p>
        <TagInput
          value={draft.escalateKeywords}
          onChange={(escalateKeywords) => patch({ escalateKeywords })}
          placeholder="complaint, fraud, urgent…"
        />
      </div>
      <Textarea
        label="Escalation message"
        value={draft.escalationMessage}
        onChange={(e) => patch({ escalationMessage: e.target.value })}
        rows={2}
      />
      <Alert tone="warning" title="Write these carefully">
        The linter flags a profile when a forbidden term leaks back into its own copy. Keep the two lists
        disjoint.
      </Alert>
    </StepShell>
  )
}

function ReviewStep({
  draft,
  onEdit,
  approvalMode,
  companyEditable,
}: {
  draft: WizardDraft
  onEdit: (step: number) => void
  approvalMode: boolean
  companyEditable: boolean
}) {
  const v = getVertical(draft.vertical)
  const answers = Object.entries(draft.answers).filter(([, value]) =>
    Array.isArray(value) ? value.length : Boolean(value),
  )

  const rows: { label: string; value: React.ReactNode; step: number }[] = [
    { label: 'Company', value: draft.companyName || '—', step: 0 },
    { label: 'Tenant id', value: draft.tenantId || '—', step: 0 },
    { label: 'Field', value: v.label, step: 0 },
    { label: 'Website', value: draft.website || '—', step: 0 },
    { label: 'Phone number id', value: draft.wabaPhoneId || 'not bound', step: 1 },
    {
      label: 'Working hours',
      value: draft.alwaysOpen
        ? 'Always open'
        : `${draft.openTime}–${draft.closeTime} · ${draft.timezone} · ${draft.openDays.length} day(s)`,
      step: 1,
    },
    { label: 'Bot name', value: draft.botName || v.label, step: 2 },
    { label: 'Tone', value: draft.tone, step: 2 },
    { label: 'Support', value: [draft.supportEmail, draft.supportPhone].filter(Boolean).join(' · ') || '—', step: 2 },
    { label: 'Calls it', value: v.nouns.item, step: 2 },
    {
<<<<<<< HEAD
      label: 'Capabilities',
      value: (
        <span className="flex flex-wrap gap-1.5">
          {FEATURE_GROUPS.flatMap((g) => g.flags)
            .filter((f) => on.has(f) && f !== 'handoff')
            .map((f) => (
              <span key={f} className="rounded bg-surface-panel px-1.5 py-0.5 text-xs text-slate-300">
                {FEATURE_LABELS[f].label}
              </span>
            ))}
        </span>
      ),
      step: 3,
    },
    {
=======
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
      label: 'Business answers',
      value: answers.length ? (
        <ul className="space-y-1">
          {answers.map(([key, value]) => (
            <li key={key} className="text-xs text-slate-300">
              <span className="text-slate-500">{key.replace(/_/g, ' ')}:</span>{' '}
              {Array.isArray(value) ? value.join(', ') : value}
            </li>
          ))}
        </ul>
      ) : (
        '—'
      ),
      step: 3,
    },
    {
      label: 'Notifications',
      value:
        [draft.salesEmail, draft.notificationsSupportEmail].filter(Boolean).join(' · ') ||
        'none configured',
      step: 4,
    },
    {
      label: 'Never state',
      value: draft.neverState ? draft.neverState.split('\n').filter(Boolean).length + ' rule(s)' : '—',
      step: 5,
    },
  ]

  return (
    <StepShell
      title={approvalMode ? 'Review and submit' : 'Review and publish'}
      description={
        approvalMode
          ? 'Submitting sends everything you added to a super admin for approval. The company basics were set by the super admin and stay read-only. Nothing goes live until they accept it.'
          : 'Creating the tenant registers it, saves this as the draft, then publishes version 1. If validation fails, nothing is published and you can fix it in the profile editor.'
      }
      icon={<BadgeCheck className="h-4 w-4" />}
    >
      <div className="divide-y divide-surface-line rounded-lg ring-1 ring-inset ring-surface-line">
        {rows.map((row) => (
          <div key={row.label} className="flex items-start gap-4 px-4 py-3">
            <span className="w-40 shrink-0 text-xs text-slate-500">{row.label}</span>
            <span className="min-w-0 flex-1 text-xs text-slate-200">
              {typeof row.value === 'string' ? row.value : row.value}
            </span>
            {(companyEditable || row.step > 0) && (
              <button
                type="button"
                onClick={() => onEdit(row.step)}
                className="shrink-0 text-xs text-accent-700 hover:text-accent-700"
              >
                Edit
              </button>
            )}
          </div>
        ))}
      </div>

      <Alert tone="info" title="What approval does">
        On approval the snapshot is merged over the {v.short} defaults, validated, stored as an immutable
        version, and the runtime cache is purged — so the next message is answered by the profile above.
      </Alert>
    </StepShell>
  )
}

// ── helpers ────────────────────────────────────────────────────────────────

interface StepProps {
  draft: WizardDraft
  patch: (values: Partial<WizardDraft>) => void
}

function answerValue(draft: WizardDraft, key: string): string {
  const value = draft.answers[key]
  if (Array.isArray(value)) return value.join(', ')
  return typeof value === 'string' ? value : ''
}

function validationError(
  stepId: StepId,
  draft: WizardDraft,
  idTaken: boolean,
  tenantSelected: boolean,
): string | null {
  switch (stepId) {
    case 'company':
      if (!draft.companyName.trim()) return 'A company name is required.'
      if (!draft.tenantId.trim()) return 'A tenant id is required.'
      if (idTaken) return 'That tenant id is already registered.'
      return null
    case 'tenant':
      if (!tenantSelected) return 'Pick the tenant you are completing.'
      return null
    case 'whatsapp': {
      if (!draft.wabaPhoneId.trim()) return 'A WhatsApp phone number id is required.'
      if (!WABA_ID_RE.test(draft.wabaPhoneId.trim()))
        return 'The WhatsApp phone number id must contain digits only.'
      if (!draft.timezone.trim()) return 'Select a timezone.'
      if (!draft.alwaysOpen && draft.openDays.length === 0) return 'Pick at least one working day.'
      return null
    }
    case 'brand': {
      if (!draft.botName.trim()) return 'Give the bot a name.'
      if (!draft.supportEmail.trim()) return 'A support email is required.'
      if (!EMAIL_RE.test(draft.supportEmail.trim()))
        return 'The support email does not look valid.'
      if (!draft.supportPhone.trim()) return 'A support phone number is required.'
      if (!isValidPhone(draft.supportPhone))
        return 'The support phone must be a country code followed by a 10-digit number, e.g. +91 98765 43210.'
      return null
    }
    case 'domain': {
      const v = getVertical(draft.vertical)
      const missing = v.questions.filter((q) => q.required && !answerValue(draft, q.key))
      if (missing.length) return `Still needed: ${missing.map((q) => q.label).join(', ')}.`
      return null
    }
    case 'notifications': {
      if (!draft.salesEmail.trim()) return 'A sales / enquiries email is required — leads need a destination.'
      if (!EMAIL_RE.test(draft.salesEmail.trim()))
        return 'The sales / enquiries email does not look valid.'
      if (draft.notificationsSupportEmail.trim() && !EMAIL_RE.test(draft.notificationsSupportEmail.trim()))
        return 'The notifications support email does not look valid.'
      return null
    }
    case 'guardrails':
      if (draft.forbiddenTerms.some((t) => draft.neverState.toLowerCase().includes(t.toLowerCase())))
        return 'A forbidden term also appears in your "never state" list.'
      return null
    default:
      return null
  }
}
