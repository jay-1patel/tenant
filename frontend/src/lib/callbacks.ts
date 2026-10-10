/**
 * Callback booking — one tenant's callback requests as the backend stores
 * them (routes/callbacks.py): one JSON document per request, keyed by id.
 *
 * Requests are normally raised by customers through WhatsApp; the console
 * client covers manual creation and the agent-side lifecycle (schedule with
 * a Google Meet link, complete, cancel).
 */

import { api } from './api'

export const CALLBACK_STATUSES = [
  'pending',
  'confirmed',
  'scheduled',
  'in_progress',
  'completed',
  'cancelled',
  'no_show',
] as const

export const CALLBACK_TYPES = ['sales', 'support', 'technical', 'general', 'follow_up'] as const

export const CALLBACK_PRIORITIES = ['low', 'medium', 'high', 'urgent'] as const

export interface Callback {
  id: string
  tenant_id: string
  wa_id: string
  customer_name: string
  customer_email: string | null
  customer_phone: string | null
  callback_type: string
  priority: string
  preferred_date: string | null
  preferred_time: string | null
  purpose: string
  additional_info: string
  assigned_agent_id: string | null
  assigned_agent_name: string | null
  meet_link: string | null
  status: string
  scheduled_start_time: string | null
  scheduled_end_time: string | null
  created_at: string
  updated_at: string
}

export interface CallbackInput {
  customer_name: string
  wa_id: string
  callback_type: string
  purpose?: string
  customer_email?: string
  customer_phone?: string
  priority?: string
  preferred_date?: string
  preferred_time?: string
  additional_info?: string
}

export interface ScheduleInput {
  agent_id: string
  agent_name: string
  start_time: string
  end_time: string
  send_notifications?: boolean
}

const base = (tenantId: string) =>
  `/api/tenants/${encodeURIComponent(tenantId)}/callbacks`

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const tail = search.toString()
  return tail ? `?${tail}` : ''
}

export const callbacksApi = {
  list: (
    tenantId: string,
    opts: { status?: string; wa_id?: string; limit?: number } = {},
    signal?: AbortSignal,
  ) =>
    api.get<{ ok: boolean; callbacks: Callback[]; total_count: number }>(
      `${base(tenantId)}${query(opts)}`,
      signal,
    ),

  create: (tenantId: string, body: CallbackInput) =>
    api.post<{ ok: boolean; callback_id: string; message: string }>(base(tenantId), body),

  cancel: (tenantId: string, callbackId: string, reason = '') =>
    api.post<{ ok: boolean; message: string }>(
      `${base(tenantId)}/${encodeURIComponent(callbackId)}/cancel`,
      { reason },
    ),

  complete: (tenantId: string, callbackId: string, meetingNotes = '', outcome = 'success') =>
    api.post<{ ok: boolean; message: string }>(
      `${base(tenantId)}/${encodeURIComponent(callbackId)}/complete`,
      { meeting_notes: meetingNotes, outcome },
    ),

  schedule: (tenantId: string, callbackId: string, body: ScheduleInput) =>
    api.post<{ ok: boolean; meet_link: string | null; message?: string }>(
      `${base(tenantId)}/${encodeURIComponent(callbackId)}/schedule`,
      body,
    ),
}
