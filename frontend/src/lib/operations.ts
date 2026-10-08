/**
 * Operational data — customers, orders, campaigns and distributors.
 *
 * Campaigns and distributors are tenant-scoped (the tenant is a path segment
 * and the server refuses a token that belongs to another one). Customers and
 * orders still read the shared platform tables; grouping them here means
 * moving them under the same prefix later is a one-file change.
 */

import { api } from './api'

const tenantBase = (tenantId: string) => `/api/admin/tenants/${encodeURIComponent(tenantId)}`

function query(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const tail = search.toString()
  return tail ? `?${tail}` : ''
}

export interface Customer {
  wa_id: string
  name: string
  mobile: string | null
  total_orders: number
  total_complaints: number
  open_complaints: number
  total_spent: number
  last_active: string | null
}

export interface OrderItem {
  name?: string
  qty?: number
  price?: number
  unit?: string
}

export interface Order {
  id: number
  order_number: string | null
  wa_id: string | null
  customer_name: string | null
  customer_mobile: string | null
  order_type: string | null
  status: string | null
  payment_status: string | null
  total_amount: number | null
  items: OrderItem[]
  notes: string | null
  created_at: string | null
}

export interface OrderCounts {
  total: number
  placed: number
  delivered: number
  cancelled: number
  revenue: number
}

export interface CampaignMetrics {
  sent: number
  delivered: number
  read: number
  replied: number
  failed: number
}

export interface Campaign {
  id: number
  name: string
  status: string
  campaign_type: string
  audience_type: string
  whatsapp_template: string
  segment: Record<string, unknown> | null
  target_count: number
  template_type: string
  message_template: string
  template_variables: Record<string, unknown>
  buttons: unknown[]
  list_items: unknown[]
  media_filename: string | null
  schedule_mode: string
  scheduled_at: string | null
  timezone: string
  metrics: CampaignMetrics
  created_at: string | null
}

/** An approved WhatsApp template the campaign builder broadcasts through. */
export interface CampaignTemplate {
  id: number
  name: string
  category: string
  body: string
  status: string
  created_at: string | null
  updated_at: string | null
}

/** A named audience derived from the tenant's own data (tiers / regions). */
export interface CampaignSegmentOption {
  id: string
  label: string
  segment: Record<string, unknown>
}

export interface CampaignStats {
  total_sent_24h: number
  delivery_rate: number
  reply_rate: number
  active_campaigns: number
}

export interface Distributor {
  wa_id: string
  name: string
  phone: string
  email: string
  region: string
  city: string
  address: string
  service_area: string
  tier: string
  product_interests: string[]
  sales_volume: number
  last_order_value: number
  outstanding_payments: number
  notes: string
}

/** Body for POST /api/distributors; PUT accepts any subset of it. */
export interface DistributorInput {
  wa_id?: string
  name?: string
  phone?: string
  email?: string
  region?: string
  city?: string
  address?: string
  service_area?: string
  tier?: string
  product_interests?: string[]
  sales_volume?: number
  outstanding_payments?: number
  notes?: string
}

/** Body for POST/PUT /api/campaigns (PUT replaces every column). */
export interface CampaignInput {
  name: string
  status: string
  campaign_type?: string
  audience_type: string
  whatsapp_template?: string
  segment?: Record<string, unknown> | null
  template_type?: string
  message_template: string
  template_variables?: Record<string, unknown>
  buttons?: unknown[]
  list_items?: unknown[]
  media_filename?: string | null
  schedule_mode: string
  scheduled_at?: string | null
  timezone?: string
}

export const operationsApi = {
  customers: (opts: { q?: string; limit?: number } = {}, signal?: AbortSignal) =>
    api.get<{ customers: Customer[]; count: number }>(`/api/admin/customers${query(opts)}`, signal),

  orders: (
    opts: { status?: string; order_type?: string; payment_status?: string; q?: string; limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    api.get<{ orders: Order[]; count: number; counts: OrderCounts }>(`/api/orders${query(opts)}`, signal),

  campaigns: (tenantId: string, signal?: AbortSignal) =>
    api.get<{ campaigns: Campaign[]; stats: CampaignStats }>(
      `${tenantBase(tenantId)}/campaigns`,
      signal,
    ),

  distributors: (
    tenantId: string,
    opts: { q?: string; region?: string; tier?: string } = {},
    signal?: AbortSignal,
  ) =>
    api.get<{ distributors: Distributor[] }>(
      `${tenantBase(tenantId)}/distributors${query(opts)}`,
      signal,
    ),

  createDistributor: (tenantId: string, body: DistributorInput & { wa_id: string }) =>
    api.post<{ ok: boolean; wa_id: string }>(`${tenantBase(tenantId)}/distributors`, body),

  updateDistributor: (tenantId: string, waId: string, body: DistributorInput) =>
    api.put<{ ok: boolean }>(`${tenantBase(tenantId)}/distributors/${encodeURIComponent(waId)}`, body),

  deleteDistributor: (tenantId: string, waId: string) =>
    api.del<{ ok: boolean }>(`${tenantBase(tenantId)}/distributors/${encodeURIComponent(waId)}`),

  campaignTemplates: (tenantId: string, signal?: AbortSignal) =>
    api.get<{ templates: CampaignTemplate[] }>(
      `${tenantBase(tenantId)}/campaigns/templates`,
      signal,
    ),

  createCampaignTemplate: (
    tenantId: string,
    body: { name: string; category: string; body: string },
  ) =>
    api.post<{ ok: boolean; id: number }>(
      `${tenantBase(tenantId)}/campaigns/templates`,
      body,
    ),

  setCampaignTemplateStatus: (tenantId: string, id: number, status: string) =>
    api.put<{ ok: boolean }>(`${tenantBase(tenantId)}/campaigns/templates/${id}`, {
      status,
    }),

  campaignSegments: (tenantId: string, signal?: AbortSignal) =>
    api.get<{ segments: CampaignSegmentOption[] }>(
      `${tenantBase(tenantId)}/campaigns/segments`,
      signal,
    ),

  createCampaign: (tenantId: string, body: CampaignInput) =>
    api.post<{ ok: boolean; id: number }>(`${tenantBase(tenantId)}/campaigns`, body),

  updateCampaign: (tenantId: string, campaignId: number, body: CampaignInput) =>
    api.put<{ ok: boolean }>(`${tenantBase(tenantId)}/campaigns/${campaignId}`, body),

  deleteCampaign: (tenantId: string, campaignId: number) =>
    api.del<{ ok: boolean }>(`${tenantBase(tenantId)}/campaigns/${campaignId}`),
}

export const ORDER_STATUSES = [
  'placed',
  'confirmed',
  'processing',
  'shipped',
  'delivered',
  'completed',
  'cancelled',
  'returned',
]

export const DISTRIBUTOR_TIERS = ['Bronze', 'Silver', 'Gold', 'Platinum']

/** `₹1,234` / `—` for null-ish totals. */
export function money(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return `₹${Number(value).toLocaleString('en-IN')}`
}
