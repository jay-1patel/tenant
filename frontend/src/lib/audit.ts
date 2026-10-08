import { api } from './api'

export type AuditOutcome = 'success' | 'failure'

export interface AuditEvent {
  id: number
  created_at: string
  actor_id: number | null
  actor_username: string | null
  actor_role: string | null
  action: string
  outcome: AuditOutcome
  resource_type: string
  resource_id: string
  target_username: string | null
  tenant_id: string | null
  details: Record<string, unknown>
}

export interface AuditFilters {
  start_date?: string
  end_date?: string
  actor?: string
  action?: string
  category?: string
  tenant_id?: string
  outcome?: AuditOutcome | ''
  search?: string
  limit?: number
  offset?: number
}

export interface AuditPage {
  events: AuditEvent[]
  total: number
  limit: number
  offset: number
}

export const auditApi = {
  list: (filters: AuditFilters, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    return api.get<AuditPage>(`/api/admin/audit-history?${query.toString()}`, signal)
  },
}
