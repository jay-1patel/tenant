import type {
  AdminIdentity,
  Agent,
  ChatTurn,
  Complaint,
  ConversationThread,
  InboxItem,
  LayerDetail,
  Offering,
  RecordSchema,
  ResolvedProfile,
  SmokeReport,
  Tenant,
  TenantToken,
  TestQuestionResult,
  VersionRecord,
} from '@/lib/types'

const features = Object.fromEntries(
  [
    'cart', 'buy_now', 'orders', 'track_order', 'returns', 'brochure_pdf',
    'distributors', 'offerings', 'offering_details', 'lead_capture', 'quote',
    'callback', 'book_appointment', 'handoff', 'faq', 'kb', 'complaints',
    'campaigns', 'human_handover',
  ].map((k) => [k, true]),
)

export const tenant: Tenant = {
  id: 'acme',
  slug: 'acme',
  vertical: 'ecommerce',
  display_name: 'Acme Retail',
  waba_phone_id: '111',
  status: 'active',
  current_version: 2,
  created_at: '2025-01-01T00:00:00Z',
}

export const tenants: Tenant[] = [tenant]

export const identity: AdminIdentity = {
  id: 1,
  username: 'root',
  role: 'super_admin',
  email: 'root@example.com',
  permissions: {},
}

export const resolved: ResolvedProfile = {
  tenant_id: 'acme',
  vertical: 'ecommerce',
  version: 2,
  source: 'db',
  features: features as ResolvedProfile['features'],
  vocabulary: { greeting: 'Hi there' },
  brand: {
    name: 'Acme Retail',
    tagline: 'Stuff you need',
    website: 'https://acme.example',
    support_email: 'support@acme.example',
    support_phone: '+91 00000 00000',
    signature: '— Team Acme',
    bot_name: 'Acme Bot',
  },
  business_hours: {
    timezone: 'Asia/Kolkata',
    always_open: true,
    open: '09:00',
    close: '18:00',
    open_days: [0, 1, 2, 3, 4, 5, 6],
    out_of_hours_message: 'We are closed',
  },
  guardrails: {
    never_state: ['We are cheapest'],
    never_state_notes: {},
    escalate_keywords: ['lawyer'],
    escalation_message: 'Escalating',
    forbidden_terms: ['guarantee'],
    handoff_keywords: ['human'],
  },
  notifications: {
    sales_email: 'sales@acme.example',
    support_email: 'support@acme.example',
    brochure_url: 'https://acme.example/brochure',
    brochure_label: 'Brochure',
    channels: [
      { type: 'email', to: 'sales@acme.example', label: 'Sales', enabled: true, secret: '' },
    ],
  },
  menu: {
    key: 'main',
    header: 'Acme Menu',
    body: 'What can we help with?',
    footer: 'Reply with a number',
    button_text: 'Options',
    buttons: [
      {
        id: 'menu_help',
        title: 'Help',
        description: 'Get help',
        section: 'main',
        icon: 'help',
        sort_order: 0,
        requires_feature: null,
        out_of_hours_only: false,
        flow: null,
        intent: 'greeting',
      },
    ],
  },
  active_intents: [
    { name: 'greeting', examples: ['hi'], keywords: ['hello'], requires_feature: null, flow: null, enabled: true },
  ],
  inactive_intents: [],
  flows: [
    {
      name: 'order_flow',
      intent: 'place_order',
      requires_feature: 'orders',
      description: 'Order something',
      start_message: 'Let’s order',
      success_message: 'Done',
      failure_message: 'Failed',
      out_of_hours_variant: null,
      steps: [
        {
          id: 's1', type: 'ask', prompt: 'What do you need?', key: 'item',
          validate: 'non_empty', optional: false, invalid_message: 'Try again',
          max_attempts: 3, options: [], yes_label: 'Yes', no_label: 'No',
          message: '', collect_keys: [], lead_source: '', channels: [],
          subject: '', handoff_reason: '', store_context: false, on: {},
          next: '', goto: '',
        },
      ],
    },
  ],
}

export const versions: { tenant_id: string; current_version: number; versions: VersionRecord[] } = {
  tenant_id: 'acme',
  current_version: 2,
  versions: [
    { version: 2, is_current: 1, created_at: '2025-02-01T00:00:00Z', published_by: 'root', note: 'latest' },
    { version: 1, is_current: 0, created_at: '2025-01-01T00:00:00Z', published_by: 'root', note: 'first' },
  ],
}

export const versionSnapshot = {
  vertical: 'ecommerce',
  brand: { name: 'Acme Retail v1' },
}

export const tokens: TenantToken[] = [
  {
    id: 1,
    tenant_id: 'acme',
    label: 'prod',
    created_by: 'root',
    created_at: '2025-01-01T00:00:00Z',
    revoked_at: null,
    last_used_at: '2025-02-01T00:00:00Z',
  },
]

export const smoke: SmokeReport = {
  tenant_id: 'acme',
  vertical: 'ecommerce',
  version: 2,
  visible_buttons: ['menu_help'],
  active_intents: ['greeting'],
  gated_intents: { order_flow: true },
  forbidden_term_leaks: [],
  ok: true,
}

export const layerDetail: LayerDetail = {
  tenant,
  layers: { defaults: {}, file: {}, db: {} },
  current_version: 2,
  versions: versions.versions,
  effective: resolved,
  effective_error: null,
}

export const offerings: Offering[] = [
  {
    id: 1,
    name: 'Widget',
    slug: 'widget',
    category: 'products',
    short_label: null,
    short_description: 'A widget',
    description: 'A very good widget',
    price: '₹100',
    detail_url: null,
    media_url: null,
    media_type: 'image',
    attrs: {},
    sort_order: 0,
    is_active: true,
  },
]

export const recordSchema: RecordSchema = {
  tenant_id: 'acme',
  vertical: 'ecommerce',
  columns: [
    { id: 1, key: 'name', label: 'Name', type: 'text', required: true, options: [], help: '', sort_order: 0, is_system: true },
    { id: 2, key: 'city', label: 'City', type: 'select', required: false, options: ['Mumbai', 'Pune'], help: '', sort_order: 1, is_system: false },
  ],
}

export const records = [
  { id: 1, name: 'Widget', city: 'Mumbai', is_active: true, sort_order: 0, created_at: '2025-01-01T00:00:00Z', updated_at: null, slug: 'widget' },
]

export const threads: ConversationThread[] = [
  {
    wa_id: '911111111111',
    name: 'Priya',
    last_message: 'I need help',
    last_at: '2025-02-01T10:00:00Z',
    turns: 4,
    inbound: 2,
    handover: false,
    bot_state: null,
  },
]

export const turns: ChatTurn[] = [
  {
    id: 1,
    wa_id: '911111111111',
    sender_name: 'Priya',
    message: '[faq] I need help',
    response: 'How can I help?',
    route: 'faq',
    created_at: '2025-02-01T10:00:00Z',
    user_message: 'I need help',
  },
]

export const inbox: InboxItem[] = [
  {
    wa_id: '911111111111',
    name: 'Priya',
    last_message: 'I need help',
    last_message_at: '2025-02-01T10:00:00Z',
    turns: 4,
    bot_state: null,
    handover_mode: 'human',
    assigned_agent_id: null,
  },
]

export const agents: Agent[] = [
  { agent_id: 'root', username: 'root', status: 'online' },
]

export const complaints: Complaint[] = [
  {
    id: 1,
    ticket_id: 'T-1',
    wa_id: '911111111111',
    complaint_type: 'delivery',
    description: 'Late delivery',
    status: 'open',
    priority: 'high',
    subject: 'Late delivery',
    assigned_to: null,
    resolved_at: null,
    updated_at: '2025-02-01T00:00:00Z',
    created_at: '2025-02-01T00:00:00Z',
    name: 'Priya',
    last_user_message: 'Where is my order?',
  },
]

export const campaigns = [
  {
    id: 1,
    name: 'Diwali blast',
    status: 'draft',
    audience_type: 'all',
    segment: null,
    target_count: 10,
    template_type: 'text',
    message_template: 'Happy {{name}}',
    template_variables: { name: 'Diwali' },
    buttons: [],
    list_items: [],
    media_filename: null,
    schedule_mode: 'now',
    scheduled_at: null,
    timezone: 'Asia/Kolkata',
    metrics: { sent: 10, delivered: 9, read: 8, replied: 2, failed: 1 },
    created_at: '2025-02-01T00:00:00Z',
  },
]

export const campaignStats = { total_sent_24h: 10, delivery_rate: 90, reply_rate: 20, active_campaigns: 1 }

export const distributors = [
  {
    wa_id: '912222222222',
    name: 'Ravi Traders',
    phone: '+91 22222 22222',
    email: 'ravi@example.com',
    region: 'West',
    tier: 'Gold',
    product_interests: ['widgets'],
    sales_volume: 1000,
    last_order_value: 200,
    outstanding_payments: 50,
    notes: 'key partner',
  },
]

export const customers = [
  {
    wa_id: '911111111111',
    name: 'Priya',
    mobile: '+91 11111 11111',
    total_orders: 3,
    total_complaints: 1,
    open_complaints: 0,
    total_spent: 1200,
    last_active: '2025-02-01T00:00:00Z',
  },
]

export const orders = [
  {
    id: 1,
    order_number: 'A-1',
    wa_id: '911111111111',
    customer_name: 'Priya',
    customer_mobile: '+91 11111 11111',
    order_type: 'order',
    status: 'placed',
    payment_status: 'paid',
    total_amount: 500,
    items: [{ name: 'Widget', qty: 2, price: 250, unit: 'pcs' }],
    notes: null,
    created_at: '2025-02-01T00:00:00Z',
  },
]

export const orderCounts = { total: 1, placed: 1, delivered: 0, cancelled: 0, revenue: 500 }

export const files = [
  {
    id: 1,
    name: 'faq.pdf',
    ext: 'pdf',
    module: 'faq',
    size: 1024,
    doc_id: 1,
    file_path: '/x/faq.pdf',
    url: null,
    tenant_id: 'acme',
    created_at: '2025-01-01T00:00:00Z',
  },
]

export const admins = [
  {
    username: 'root',
    email: 'root@example.com',
    role: 'super_admin',
    permissions: {},
    created_at: '2025-01-01T00:00:00Z',
  },
  {
    username: 'helper',
    email: 'helper@example.com',
    role: 'sub_admin',
    permissions: { view_customers: true },
    created_at: '2025-01-02T00:00:00Z',
  },
]

export const chatUsers = [{ wa_id: '911111111111', name: 'Priya' }]

export const testQuestion: TestQuestionResult = {
  tenant_id: 'acme',
  message: 'hi',
  intent: 'greeting',
  score: 0.9,
  tier: 'high',
  flow: null,
  active_intents: ['greeting'],
}

export const fixtures = {
  tenant,
  tenants,
  identity,
  resolved,
  versions,
  versionSnapshot,
  tokens,
  smoke,
  layerDetail,
  offerings,
  recordSchema,
  records,
  threads,
  turns,
  inbox,
  agents,
  complaints,
  campaigns,
  campaignStats,
  distributors,
  customers,
  orders,
  orderCounts,
  files,
  admins,
  chatUsers,
  testQuestion,
}
