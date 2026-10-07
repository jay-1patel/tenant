import { api } from './api'

export type ApiOnboardingType = 'payment_api' | 'order_api'
export type ApiOnboardingStatus = 'pending' | 'approved' | 'rejected'

export interface ApiOnboardingRequest {
  id: number
  tenant_id: string
  api_type: ApiOnboardingType
  provider: string
  environment: 'sandbox' | 'production'
  purpose: string
  status: ApiOnboardingStatus
  requester_id: number | null
  requester_username: string
  reviewer_id: number | null
  reviewer_username: string | null
  decision_note: string
  decided_at: string | null
  created_at: string
  updated_at: string
  eligible?: boolean | number
}

export interface ApiProviderPreset {
  id: string
  name: string
  category: 'payment' | 'shipping'
  apiType: ApiOnboardingType
  description: string
  icon: string
  isCustom?: boolean
}

export const PAYMENT_PROVIDERS: ApiProviderPreset[] = [
  {
    id: 'stripe',
    name: 'Stripe',
    category: 'payment',
    apiType: 'payment_api',
    description: 'Global card processing, Apple Pay, Google Pay & subscription billing.',
    icon: '💳',
  },
  {
    id: 'razorpay',
    name: 'Razorpay',
    category: 'payment',
    apiType: 'payment_api',
    description: 'UPI, NetBanking, Credit/Debit cards, Wallets & EMI payments.',
    icon: '⚡',
  },
  {
    id: 'custom_payment',
    name: 'Custom Payment Gateway',
    category: 'payment',
    apiType: 'payment_api',
    description: 'Integrate any other payment gateway provider of your choice.',
    icon: '🔧',
    isCustom: true,
  },
]

export const SHIPPING_PROVIDERS: ApiProviderPreset[] = [
  {
    id: 'bluedart',
    name: 'Blue Dart',
    category: 'shipping',
    apiType: 'order_api',
    description: 'Express courier delivery, AWB tracking & shipping dispatch APIs.',
    icon: '🚚',
  },
  {
    id: 'xpressbees',
    name: 'Xpressbees',
    category: 'shipping',
    apiType: 'order_api',
    description: 'E-commerce logistics, reverse pickup, package tracking & COD support.',
    icon: '📦',
  },
  {
    id: 'custom_shipping',
    name: 'Custom Shipping Provider',
    category: 'shipping',
    apiType: 'order_api',
    description: 'Integrate any custom courier, logistics or order fulfillment API.',
    icon: '🛠️',
    isCustom: true,
  },
]

export interface ApiOnboardingEvent {
  id: number
  request_id: number
  actor_id: number | null
  actor_username: string
  actor_role: string
  event_type: 'submitted' | 'decision'
  old_status: string | null
  new_status: string
  note: string
  created_at: string
}

export interface TenantIntegration {
  id: number
  tenant_id: string
  provider: string
  api_type: ApiOnboardingType
  environment: 'sandbox' | 'production'
  is_active: number | boolean
  credentials_masked: Record<string, string>
  has_credentials: boolean
  webhook_secret: string
  status: 'configured' | 'verified' | 'error'
  last_tested_at: string | null
  last_error: string
  created_at: string
  updated_at: string
}

export interface IntegrationTestResult {
  ok: boolean
  provider: string
  status: 'verified' | 'error'
  details: {
    ok: boolean
    message?: string
    error?: string
    [key: string]: any
  }
}

export const apiOnboarding = {
  mine: async (signal?: AbortSignal) =>
    (await api.get<{ requests: ApiOnboardingRequest[] }>('/api/integration-requests', signal)).requests,
  create: async (input: {
    api_type: ApiOnboardingType
    provider: string
    environment: 'sandbox' | 'production'
    purpose: string
  }) =>
    (await api.post<{ request: ApiOnboardingRequest }>('/api/integration-requests', input)).request,
  all: async (status?: ApiOnboardingStatus, signal?: AbortSignal) => {
    const query = status ? `?status=${encodeURIComponent(status)}` : ''
    return (await api.get<{ requests: ApiOnboardingRequest[] }>(`/api/admin/integration-requests${query}`, signal)).requests
  },
  decide: async (id: number, decision: 'approved' | 'rejected', note: string) =>
    api.post<{ request: ApiOnboardingRequest; message: string }>(
      `/api/admin/integration-requests/${id}/decision`,
      { decision, note },
    ),
  events: async (id: number, signal?: AbortSignal) =>
    (await api.get<{ events: ApiOnboardingEvent[] }>(`/api/admin/integration-requests/${id}/events`, signal)).events,
}

export const tenantIntegrationsApi = {
  list: async (tenantId: string, signal?: AbortSignal) =>
    (await api.get<{ integrations: TenantIntegration[] }>(`/api/tenants/${encodeURIComponent(tenantId)}/integrations`, signal)).integrations,
  
  saveConfig: async (
    tenantId: string,
    provider: string,
    data: {
      api_type: ApiOnboardingType
      environment: 'sandbox' | 'production'
      is_active: boolean
      credentials: Record<string, any>
      webhook_secret?: string
    },
  ) =>
    api.post<{ ok: boolean; message: string; provider: string }>(
      `/api/tenants/${encodeURIComponent(tenantId)}/integrations/${encodeURIComponent(provider)}/config`,
      data,
    ),

  testConnection: async (
    tenantId: string,
    provider: string,
    data?: {
      api_type: ApiOnboardingType
      environment: 'sandbox' | 'production'
      credentials: Record<string, any>
    },
  ) =>
    api.post<IntegrationTestResult>(
      `/api/tenants/${encodeURIComponent(tenantId)}/integrations/${encodeURIComponent(provider)}/test`,
      data || { api_type: 'payment_api', environment: 'sandbox', credentials: {} },
    ),

  createPaymentSession: async (
    tenantId: string,
    data: {
      order_id: string
      amount: number
      currency?: string
      provider?: string
      description?: string
      customer_name?: string
      customer_phone?: string
      customer_email?: string
    },
  ) =>
    api.post<{
      ok: boolean
      provider: string
      order_id: string
      payment_url: string
      payment_id: string
      amount: number
      currency: string
    }>(`/api/tenants/${encodeURIComponent(tenantId)}/payments/create-session`, data),

  bookShipment: async (
    tenantId: string,
    data: {
      order_id: string
      provider?: string
      origin_pincode: string
      destination_pincode: string
      customer_name: string
      customer_phone: string
      weight_kg?: number
      item_description?: string
      cod?: boolean
      cod_amount?: number
    },
  ) =>
    api.post<{
      ok: boolean
      provider: string
      order_id: string
      awb_number: string
      tracking_url: string
      status: string
    }>(`/api/tenants/${encodeURIComponent(tenantId)}/shipping/book-shipment`, data),

  trackShipment: async (tenantId: string, awb: string) =>
    api.get<{
      ok: boolean
      awb: string
      status: string
      carrier: string
      tracking_url: string
      [key: string]: any
    }>(`/api/tenants/${encodeURIComponent(tenantId)}/shipping/track/${encodeURIComponent(awb)}`),
}
