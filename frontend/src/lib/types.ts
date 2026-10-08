/**
 * TypeScript mirrors of the backend contract.
 *
 * The source of truth is `shared/tenancy/schemas.py` (pydantic) and the routes
 * in `backend/routes/tenants.py`. Keep this file in step with those — it is a
 * transcription, not a design.
 */

export const VERTICALS = [
  'ecommerce',
  'it_software',
  'tours_travel',
  'banking',
  'finance',
  'healthcare',
  'generic',
] as const

export type Vertical = (typeof VERTICALS)[number]

export const FEATURE_FLAGS = [
  'cart',
  'buy_now',
  'orders',
  'track_order',
  'returns',
  'brochure_pdf',
  'distributors',
  'offerings',
  'offering_details',
  'lead_capture',
  'quote',
  'callback',
  'book_appointment',
  'handoff',
  'faq',
  'kb',
  'complaints',
  'campaigns',
  'human_handover',
] as const

export type FeatureFlag = (typeof FEATURE_FLAGS)[number]
export type Features = Record<FeatureFlag, boolean>

export type Vocabulary = Record<string, string>

export interface Brand {
  name: string
  tagline: string
  website: string
  support_email: string
  support_phone: string
  signature: string
  bot_name: string
}

export interface PromptSpec {
  name: string
  tone: string
  industry: string
  domain_specific_queries: string
  domain_specific_topics: string
  support_trigger_topics: string
  complex_topics: string
  listing_type: string
  keywords: string[]
  system_prompt: string
  strict_prompt: string
}

export interface BusinessHours {
  timezone: string
  always_open: boolean
  open: string
  close: string
  open_days: number[]
  out_of_hours_message: string
}

export interface Guardrails {
  never_state: string[]
  never_state_notes: Record<string, string>
  escalate_keywords: string[]
  escalation_message: string
  forbidden_terms: string[]
  handoff_keywords: string[]
}

export interface NotificationChannel {
  type: 'email' | 'webhook'
  to: string
  label: string
  enabled: boolean
  secret: string
}

export interface Notifications {
  sales_email: string
  support_email: string
  brochure_url: string
  brochure_label: string
  channels: NotificationChannel[]
}

export interface MenuButton {
  id: string
  title: string
  description: string
  section: string
  icon: string
  sort_order: number
  requires_feature: string | null
  out_of_hours_only: boolean
  flow: string | null
  intent: string | null
}

export interface MenuSpec {
  key: string
  header: string
  body: string
  footer: string
  button_text: string
  buttons: MenuButton[]
}

export interface IntentSpec {
  name: string
  examples: string[]
  keywords: string[]
  requires_feature: string | null
  flow: string | null
  /** Informational intents answer directly with this text (info-page panels). */
  answer?: string | null
  enabled: boolean
}

export interface FlowStep {
  id: string
  type: string
  prompt: string
  key: string
  validate: string
  optional: boolean
  invalid_message: string
  max_attempts: number
  options: string[]
  yes_label: string
  no_label: string
  message: string
  collect_keys: string[]
  lead_source: string
  channels: string[]
  subject: string
  handoff_reason: string
  store_context: boolean
  on: Record<string, string>
  next: string
  goto: string
}

export interface FlowSpec {
  name: string
  intent: string
  requires_feature: string | null
  description: string
  start_message: string
  success_message: string
  failure_message: string
  out_of_hours_variant: string | null
  steps: FlowStep[]
}

/** The merged, validated profile the bot reads right now. */
export interface ResolvedProfile {
  tenant_id: string
  vertical: Vertical | string
  version: number
  source: string
  features: Features
  vocabulary: Vocabulary
  brand: Brand
  business_hours: BusinessHours
  guardrails: Guardrails
  notifications: Notifications
  menu: MenuSpec
  active_intents: IntentSpec[]
  inactive_intents: IntentSpec[]
  flows: FlowSpec[]
}

/**
 * Layers merge menu buttons *by id*, so an override is a partial button keyed by
 * its id, and `__remove__: true` deletes an inherited one. See shared/tenancy/merge.py.
 */
export type MenuButtonOverride = Partial<MenuButton> & { id: string; __remove__?: boolean }

/** A partial profile layer. Deep-merged over defaults on the server. */
export interface ProfileSnapshot {
  vertical?: string
  display_name?: string
  status?: string
  features?: Partial<Features>
  vocabulary?: Partial<Vocabulary>
  brand?: Partial<Brand>
  prompt?: Partial<PromptSpec>
  menu?: Partial<Omit<MenuSpec, 'buttons'>> & { buttons?: MenuButtonOverride[] }
  flows?: FlowSpec[]
  intents?: IntentSpec[]
  guardrails?: Partial<Guardrails>
  business_hours?: Partial<BusinessHours>
  notifications?: Partial<Notifications>
}

export interface Tenant {
  id: string
  slug: string
  vertical: string
  display_name: string
  waba_phone_id: string
  status: string
  current_version?: number
  created_at?: string
  updated_at?: string
}

/**
 * One row of a tenant's content panel — a service, a destination, a package, a
 * product. The record is the same for every vertical; `attrs` carries the
 * vertical-specific detail (tech stack, itinerary, timings).
 */
export interface Offering {
  id: number
  name: string
  slug: string
  category: string
  short_label: string | null
  short_description: string
  description: string
  /** Optional: a consultancy service has no list price. */
  price: string | null
  detail_url: string | null
  media_url: string | null
  media_type: string
  attrs: Record<string, string>
  /** Values for the tenant's own columns, keyed by column key. */
  values?: Record<string, string | number | boolean | null>
  sort_order: number
  is_active: boolean
  created_at?: string
  updated_at?: string
}

export type OfferingInput = Omit<Offering, 'id' | 'slug' | 'created_at' | 'updated_at'>

/** The types an admin can pick for a record column. Mirrors records.COLUMN_TYPES. */
export type RecordColumnType =
  | 'text'
  | 'long_text'
  | 'number'
  | 'integer'
  | 'boolean'
  | 'date'
  | 'select'

export interface RecordColumn {
  id: number
  key: string
  label: string
  type: RecordColumnType
  required: boolean
  options: string[]
  help: string
  sort_order: number
  /** Core columns the bot reads by name — cannot be removed. */
  is_system: boolean
  created_at?: string
}

export interface RecordSchema {
  tenant_id: string
  vertical: string
  columns: RecordColumn[]
}

// ── conversations ──────────────────────────────────────────────────────────

/** One customer thread, as listed in the chat-history and inbox screens. */
export interface ConversationThread {
  wa_id: string
  name: string
  last_message: string
  last_at: string
  turns: number
  inbound: number
  handover: boolean
  bot_state: string | null
}

/** A single stored turn: the customer's line and the bot's reply. */
export interface ChatTurn {
  id: number
  wa_id: string
  sender_name: string
  /** Stored as `[route] user message`. */
  message: string
  response: string
  route: string
  created_at: string
  tenant_id?: string | null
  /** Server-computed: `message` with the `[route]` prefix stripped. */
  user_message?: string
}

export interface InboxItem {
  wa_id: string
  name: string
  last_message: string
  last_message_at: string
  turns: number
  bot_state: string | null
  handover_mode: 'bot' | 'human'
  assigned_agent_id: string | null
}

export interface Agent {
  agent_id: string
  username: string
  status: string
}

export interface Complaint {
  id: number
  ticket_id: string
  wa_id: string
  complaint_type: string
  description: string
  status: string
  priority: string
  subject: string
  assigned_to: string | null
  resolved_at: string | null
  updated_at: string
  created_at: string
  tenant_id?: string | null
  name?: string
  last_user_message?: string
}

export interface VersionRecord {
  version: number
  is_current: boolean | number
  created_at: string
  published_by: string
  note: string
}

export interface LayerDetail {
  tenant: Tenant | null
  layers: {
    defaults: Record<string, unknown>
    file: Record<string, unknown>
    db: Record<string, unknown>
  }
  current_version: number
  versions: VersionRecord[]
  effective: ProfileSnapshot | null
  effective_error: string | null
  /** The working draft merged over the file baseline — what publish would go live. */
  has_draft?: boolean
  pending?: ProfileSnapshot | null
  pending_error?: string | null
}

export interface TenantToken {
  id: number
  tenant_id: string
  label: string
  created_by: string
  created_at: string
  revoked_at: string | null
  last_used_at: string | null
}

export interface SmokeReport {
  tenant_id: string
  vertical: string
  version: number
  visible_buttons: string[]
  active_intents: string[]
  gated_intents: Record<string, boolean>
  forbidden_term_leaks: string[]
  ok: boolean
}

export interface TestQuestionResult {
  tenant_id: string
  message: string
  intent: string | null
  score: number
  tier: string
  flow: string | null
  active_intents: string[]
}

export interface AdminIdentity {
  id: number
  username: string
  role: 'super_admin' | 'admin' | 'sub_admin' | string
  email: string | null
  permissions: Record<string, boolean>
  tenant_id?: string | null
}

export interface PublishResult {
  ok: boolean
  tenant_id: string
  version: number
  vertical: string
  active_intents: string[]
  visible_buttons: string[]
}
