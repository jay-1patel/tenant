/**
 * The bridge between the registration wizard (plain form state) and the
 * server-side profile layer.
 *
 * The server deep-merges a snapshot over the vertical defaults, and lists
 * *replace* rather than append. So the rule this file follows is: only send a
 * field the operator actually filled in. An omitted key keeps the vertical's
 * curated default; an empty list would wipe it.
 */

import {
  FEATURE_FLAGS,
  type Brand,
  type BusinessHours,
  type FeatureFlag,
  type Features,
  type Guardrails,
  type Notifications,
  type ProfileSnapshot,
  type PromptSpec,
  type ResolvedProfile,
  type Tenant,
} from './types'
import { getVertical } from './verticals'

// ── shared wizard/editor data ───────────────────────────────────────────────

/**
 * The timezone dropdown shared by the registration wizard and the profile
 * editor — free text invited typos that broke the out-of-hours logic.
 */
export const TIMEZONES = [
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

/** The dropdown's option list, keeping a stored value that is not in the list. */
export function timezoneOptions(current: string): string[] {
  return TIMEZONES.includes(current) || !current ? TIMEZONES : [current, ...TIMEZONES]
}

// ── shared contact-field validators ───────────────────────────────────────
// Mirrored server-side in shared/tenancy/schemas.py: an empty value passes,
// a filled-in one must look like a real email / phone (with country code) /
// URL. Used by both the registration wizard and the profile editor.

export const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
// Country code (+91…) followed by a 10-digit number, spaces/dashes allowed.
export const normalizePhone = (value: string) => value.replace(/[\s\-()]/g, "")

// Country calling codes. The subscriber part must be exactly 10 digits, so
// "+91 741852544" (9 digits) is rejected while "+91 98765 43210" passes.
export const COUNTRY_CODES = [
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

export const isValidPhone = (raw: string) => {
  const digits = normalizePhone(raw)
  if (!/^\+\d{9,15}$/.test(digits)) return false
  const body = digits.slice(1)
  const cc = COUNTRY_CODES.find((code) => body.startsWith(code))
  if (!cc) return false
  return /^\d{10}$/.test(body.slice(cc.length))
}

/** Scheme optional, domain required: "example.com", "https://x.io/a?b=1". */
export const URL_RE = /^(https?:\/\/)?([\w-]+\.)+[A-Za-z]{2,}(:\d+)?(\/\S*)?$/

/** Contact-detail errors for the profile editor. Empty array = all valid. */
export function editorContactErrors(form: EditorForm): string[] {
  const errors: string[] = []
  const brand = form.brand
  const notes = form.notifications
  // Compulsory fields — the same set the register wizard requires.
  if (!form.displayName.trim()) errors.push('A display name is required.')
  if (!brand.botName.trim()) errors.push('Give the bot a name.')
  if (!brand.supportEmail.trim()) errors.push('A support email is required.')
  if (!brand.supportPhone.trim()) errors.push('A support phone number is required.')
  if (!notes.salesEmail.trim())
    errors.push('A sales / enquiries email is required — leads need a destination.')
  if (brand.website.trim() && !URL_RE.test(brand.website.trim()))
    errors.push('The website does not look like a valid URL (e.g. https://example.com).')
  if (brand.supportEmail.trim() && !EMAIL_RE.test(brand.supportEmail.trim()))
    errors.push('The support email does not look valid.')
  if (brand.supportPhone.trim() && !isValidPhone(brand.supportPhone))
    errors.push('The support phone must include the country code, e.g. +91 98765 43210.')
  if (notes.salesEmail.trim() && !EMAIL_RE.test(notes.salesEmail.trim()))
    errors.push('The sales / enquiries email does not look valid.')
  if (notes.supportEmail.trim() && !EMAIL_RE.test(notes.supportEmail.trim()))
    errors.push('The notifications support email does not look valid.')
  if (notes.brochureUrl.trim() && !URL_RE.test(notes.brochureUrl.trim()))
    errors.push('The brochure URL does not look like a valid URL.')
  return errors
}

// ── wizard form state ──────────────────────────────────────────────────────

export interface ChannelDraft {
  type: 'email' | 'webhook'
  to: string
  label: string
}

export interface WizardDraft {
  // identity
  companyName: string
  tenantId: string
  displayName: string
  vertical: string
  website: string
  // WhatsApp binding + hours
  wabaPhoneId: string
  timezone: string
  alwaysOpen: boolean
  openTime: string
  closeTime: string
  openDays: number[]
  outOfHoursMessage: string
  // brand + voice
  botName: string
  tagline: string
  signature: string
  tone: string
  supportEmail: string
  supportPhone: string
  greeting: string
  // capabilities
  features: FeatureFlag[]
  // vertical-specific answers (chips store arrays, others strings)
  answers: Record<string, string[] | string>
  // notifications
  salesEmail: string
  notificationsSupportEmail: string
  brochureUrl: string
  channels: ChannelDraft[]
  // guardrails
  neverState: string
  escalateKeywords: string[]
  forbiddenTerms: string[]
  handoffKeywords: string[]
  escalationMessage: string
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 40)
}

export function emptyDraft(): WizardDraft {
  const v = getVertical('generic')
  return {
    companyName: '',
    tenantId: '',
    displayName: '',
    vertical: 'generic',
    website: '',
    wabaPhoneId: '',
    timezone: 'Asia/Kolkata',
    alwaysOpen: true,
    openTime: '09:00',
    closeTime: '21:00',
    openDays: [0, 1, 2, 3, 4, 5, 6],
    outOfHoursMessage:
      'We are currently outside our working hours. Leave your details and our team will call you back on the next working day.',
    botName: '',
    tagline: '',
    signature: '',
    tone: v.tone,
    supportEmail: '',
    supportPhone: '',
    greeting: '',
    features: [...v.recommended],
    answers: {},
    salesEmail: '',
    notificationsSupportEmail: '',
    brochureUrl: '',
    channels: [],
    neverState: '',
    escalateKeywords: [],
    forbiddenTerms: [],
    handoffKeywords: ['human', 'agent', 'person'],
    escalationMessage: 'Let me connect you with our team.',
  }
}

export function applyVertical(draft: WizardDraft, vertical: string): WizardDraft {
  const v = getVertical(vertical)
  return {
    ...draft,
    vertical: v.id,
    tone: v.tone,
    features: [...v.recommended],
  }
}

// ── helpers ────────────────────────────────────────────────────────────────

export function featureRecord(selected: FeatureFlag[]): Features {
  const on = new Set(selected)
  const out = {} as Features
  for (const flag of FEATURE_FLAGS) out[flag] = on.has(flag)
  return out
}

function splitLines(value: string): string[] {
  return value
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)
}

function keywordsFromAnswers(answers: WizardDraft['answers']): string[] {
  const keys = ['tech_stack', 'categories', 'trip_types', 'products', 'departments', 'services', 'offerings']
  const out: string[] = []
  for (const key of keys) {
    const value = answers[key]
    if (Array.isArray(value)) out.push(...value)
    else if (typeof value === 'string') out.push(value)
  }
  return Array.from(new Set(out.map((s) => s.trim()).filter(Boolean)))
}

// ── resolved profile → wizard draft ─────────────────────────────────────────

/**
 * Prefill the registration wizard from a tenant's resolved profile, so an
 * admin completing a super admin's registration starts from what is already
 * there instead of the vertical defaults.
 */
export function draftFromProfile(profile: ResolvedProfile, tenant: Tenant): WizardDraft {
  const brand: Partial<Brand> = profile.brand ?? {}
  const hours: Partial<BusinessHours> = profile.business_hours ?? {}
  const notes: Partial<Notifications> = profile.notifications ?? {}
  const rails: Partial<Guardrails> = profile.guardrails ?? {}
  const v = getVertical(String(profile.vertical ?? tenant.vertical ?? 'generic'))

  return {
    ...emptyDraft(),
    companyName: brand.name || tenant.display_name || tenant.id,
    tenantId: tenant.id,
    displayName: tenant.display_name || brand.name || tenant.id,
    vertical: String(profile.vertical ?? tenant.vertical ?? 'generic'),
    website: brand.website ?? '',
    wabaPhoneId: tenant.waba_phone_id ?? '',
    timezone: hours.timezone ?? 'Asia/Kolkata',
    alwaysOpen: hours.always_open ?? true,
    openTime: hours.open ?? '09:00',
    closeTime: hours.close ?? '21:00',
    openDays: Array.isArray(hours.open_days) ? hours.open_days : [0, 1, 2, 3, 4, 5, 6],
    outOfHoursMessage: hours.out_of_hours_message ?? '',
    botName: brand.bot_name ?? '',
    tagline: brand.tagline ?? '',
    signature: brand.signature ?? '',
    tone: v.tone,
    supportEmail: brand.support_email ?? '',
    supportPhone: brand.support_phone ?? '',
    greeting: (profile.menu as { body?: string } | null)?.body ?? '',
    features: FEATURE_FLAGS.filter((f) => Boolean(profile.features?.[f])),
    salesEmail: notes.sales_email ?? '',
    notificationsSupportEmail: notes.support_email ?? '',
    brochureUrl: notes.brochure_url ?? '',
    channels: (notes.channels ?? []).map((c) => ({
      type: c.type === 'email' ? 'email' : 'webhook',
      to: c.to ?? '',
      label: c.label ?? '',
    })),
    neverState: (rails.never_state ?? []).join('\n'),
    escalateKeywords: rails.escalate_keywords ?? [],
    forbiddenTerms: rails.forbidden_terms ?? [],
    handoffKeywords: rails.handoff_keywords?.length ? rails.handoff_keywords : ['human', 'agent'],
    escalationMessage: rails.escalation_message ?? '',
  }
}

// ── wizard → snapshot ──────────────────────────────────────────────────────

export function draftToSnapshot(draft: WizardDraft): ProfileSnapshot {
  const v = getVertical(draft.vertical)
  const snapshot: ProfileSnapshot = {
    vertical: v.id,
    display_name: draft.displayName || draft.companyName,
    features: featureRecord(draft.features),
    brand: {
      name: draft.companyName,
      tagline: draft.tagline,
      website: draft.website,
      support_email: draft.supportEmail,
      support_phone: draft.supportPhone,
      signature: draft.signature,
      bot_name: draft.botName,
    },
    vocabulary: {
      item_noun: v.nouns.item,
      item_noun_singular: v.nouns.itemSingular,
      browse_label: v.nouns.browse,
      catalog_label: v.nouns.catalog,
      lead_noun: v.nouns.lead,
      enquiry_label: v.nouns.leadAction,
    },
    prompt: {
      tone: draft.tone || v.tone,
      industry: v.industry,
      listing_type: v.listingType,
      domain_specific_queries: v.domainQueries,
    },
    business_hours: {
      timezone: draft.timezone,
      always_open: draft.alwaysOpen,
      open: draft.openTime,
      close: draft.closeTime,
      open_days: draft.openDays,
      out_of_hours_message: draft.outOfHoursMessage,
    },
    guardrails: {
      escalation_message: draft.escalationMessage,
      handoff_keywords: draft.handoffKeywords.length ? draft.handoffKeywords : ['human', 'agent'],
    },
  }

  const keywords = keywordsFromAnswers(draft.answers)
  if (keywords.length) snapshot.prompt = { ...snapshot.prompt!, keywords }

  const neverState = splitLines(draft.neverState)
  if (neverState.length) {
    snapshot.guardrails = { ...snapshot.guardrails!, never_state: neverState }
  }
  if (draft.escalateKeywords.length) {
    snapshot.guardrails = {
      ...snapshot.guardrails!,
      escalate_keywords: draft.escalateKeywords.map((s) => s.toLowerCase()),
    }
  }
  if (draft.forbiddenTerms.length) {
    snapshot.guardrails = { ...snapshot.guardrails!, forbidden_terms: draft.forbiddenTerms }
  }

  if (draft.greeting.trim()) {
    snapshot.menu = { header: draft.companyName, body: draft.greeting.trim() }
  }

  const channels = draft.channels
    .filter((c) => c.to.trim())
    .map((c) => ({ type: c.type, to: c.to.trim(), label: c.label.trim(), enabled: true, secret: '' }))
  const notifications: NonNullable<ProfileSnapshot['notifications']> = {}
  if (draft.salesEmail.trim()) notifications.sales_email = draft.salesEmail.trim()
  if (draft.notificationsSupportEmail.trim()) {
    notifications.support_email = draft.notificationsSupportEmail.trim()
  }
  if (draft.brochureUrl.trim()) notifications.brochure_url = draft.brochureUrl.trim()
  if (channels.length) notifications.channels = channels
  if (Object.keys(notifications).length) snapshot.notifications = notifications

  return snapshot
}

// ── resolved profile → editor form ─────────────────────────────────────────

export interface EditorForm {
  displayName: string
  vertical: string
  features: FeatureFlag[]
  brand: {
    name: string
    botName: string
    tagline: string
    website: string
    supportEmail: string
    supportPhone: string
    signature: string
  }
  vocabulary: Record<string, string>
  businessHours: {
    timezone: string
    alwaysOpen: boolean
    open: string
    close: string
    openDays: number[]
    outOfHoursMessage: string
  }
  notifications: {
    salesEmail: string
    supportEmail: string
    brochureUrl: string
  }
  guardrails: {
    neverState: string
    escalateKeywords: string
    forbiddenTerms: string
    handoffKeywords: string
    escalationMessage: string
  }
  keywords: string
}

export function editorFromProfile(profile: ProfileSnapshot): EditorForm {
  const hours: Partial<BusinessHours> = profile.business_hours ?? {}
  const notes: Partial<Notifications> = profile.notifications ?? {}
  const rails: Partial<Guardrails> = profile.guardrails ?? {}
  const prompt: Partial<PromptSpec> = profile.prompt ?? {}
  const brand: Partial<Brand> = profile.brand ?? {}
  const vocabulary: Record<string, string> = {}
  for (const [key, value] of Object.entries(profile.vocabulary ?? {})) {
    if (typeof value === 'string') vocabulary[key] = value
  }

  return {
    displayName: profile.display_name || brand.name || '',
    vertical: profile.vertical ?? 'generic',
    features: FEATURE_FLAGS.filter((f) => Boolean(profile.features?.[f])),
    brand: {
      name: brand.name ?? '',
      botName: brand.bot_name ?? '',
      tagline: brand.tagline ?? '',
      website: brand.website ?? '',
      supportEmail: brand.support_email ?? '',
      supportPhone: brand.support_phone ?? '',
      signature: brand.signature ?? '',
    },
    vocabulary,
    businessHours: {
      timezone: hours.timezone ?? 'Asia/Kolkata',
      alwaysOpen: hours.always_open ?? true,
      open: hours.open ?? '09:00',
      close: hours.close ?? '21:00',
      openDays: Array.isArray(hours.open_days) ? hours.open_days : [0, 1, 2, 3, 4, 5, 6],
      outOfHoursMessage: hours.out_of_hours_message ?? '',
    },
    notifications: {
      salesEmail: notes.sales_email ?? '',
      supportEmail: notes.support_email ?? '',
      brochureUrl: notes.brochure_url ?? '',
    },
    guardrails: {
      neverState: (rails.never_state ?? []).join('\n'),
      escalateKeywords: (rails.escalate_keywords ?? []).join(', '),
      forbiddenTerms: (rails.forbidden_terms ?? []).join(', '),
      handoffKeywords: (rails.handoff_keywords ?? []).join(', '),
      escalationMessage: rails.escalation_message ?? '',
    },
    keywords: (prompt.keywords ?? []).join(', '),
  }
}

const CSV = /[,\n]/

function csv(value: string): string[] {
  return value
    .split(CSV)
    .map((s) => s.trim())
    .filter(Boolean)
}

export function editorToSnapshot(form: EditorForm): ProfileSnapshot {
  return {
    display_name: form.displayName,
    features: featureRecord(form.features),
    brand: {
      name: form.brand.name,
      bot_name: form.brand.botName,
      tagline: form.brand.tagline,
      website: form.brand.website,
      support_email: form.brand.supportEmail,
      support_phone: form.brand.supportPhone,
      signature: form.brand.signature,
    },
    vocabulary: form.vocabulary,
    business_hours: {
      timezone: form.businessHours.timezone,
      always_open: form.businessHours.alwaysOpen,
      open: form.businessHours.open,
      close: form.businessHours.close,
      open_days: form.businessHours.openDays,
      out_of_hours_message: form.businessHours.outOfHoursMessage,
    },
    notifications: {
      sales_email: form.notifications.salesEmail,
      support_email: form.notifications.supportEmail,
      brochure_url: form.notifications.brochureUrl,
    },
    guardrails: {
      never_state: form.guardrails.neverState.split('\n').map((s) => s.trim()).filter(Boolean),
      escalate_keywords: csv(form.guardrails.escalateKeywords).map((s) => s.toLowerCase()),
      forbidden_terms: csv(form.guardrails.forbiddenTerms),
      handoff_keywords: csv(form.guardrails.handoffKeywords),
      escalation_message: form.guardrails.escalationMessage,
    },
    prompt: { keywords: csv(form.keywords) },
  }
}
