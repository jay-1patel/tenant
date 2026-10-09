import { api } from './api'
import { type AuditOutcome, type AuditEvent, type AuditFilters, type AuditPage } from './audit'

// Extended audit types for new features
export interface AuditEventExtended extends Omit<AuditEvent, 'details'> {
  details: Record<string, unknown>
  ip_address?: string
  user_agent?: string
  tenant_name?: string | null
  tenant_slug?: string | null
  tenant_label?: string
  actor_kind?: string | null
  actor_label?: string | null
  category?: string
  formatted_date?: string
  relative_time?: string
}

export interface AuditStatistics {
  total_events: number
  by_outcome: {
    success: number
    failure: number
  }
  by_action: Record<string, number>
  by_date: Record<string, number>
  by_category: Record<string, number>
  by_actor: Record<string, number>
}

// Extended filters
export interface AuditFiltersExtended extends AuditFilters {
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

// Export request
export interface ExportRequest {
  filters: AuditFiltersExtended
  format: 'csv' | 'json'
  columns: string[]
}

// Realtime updates
export interface RealtimeUpdate {
  type: 'new' | 'updated' | 'deleted'
  event: AuditEventExtended
  timestamp: string
}

// Extended API functions
export const auditApiExtended = {
  // Original list function
  list: (filters: AuditFilters, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    return api.get<AuditPage>(`/api/admin/audit-history?${query.toString()}`, signal)
  },

  // New statistics endpoint
  getStatistics: (filters: AuditFilters, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    return api.get<AuditStatistics>(`/api/admin/audit-statistics?${query.toString()}`, signal)
  },

  // Export endpoint
  exportEvents: (request: ExportRequest, signal?: AbortSignal) => {
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(request.filters)) {
      if (value !== undefined && value !== '') query.set(key, String(value))
    }
    query.set('format', request.format)
    query.set('columns', request.columns.join(','))
    
    return api.get<Blob>(`/api/admin/audit-export?${query.toString()}`, signal, { 
      responseType: 'blob' 
    })
  },

  // Get single event details
  getEvent: (eventId: number, signal?: AbortSignal) => {
    return api.get<AuditEventExtended>(`/api/admin/audit-history/${eventId}`, signal)
  },

  // Real-time updates (WebSocket simulation via polling for now)
  subscribeUpdates: (callback: (update: RealtimeUpdate) => void, signal?: AbortSignal) => {
    // This would be implemented with WebSocket in a real scenario
    // For now, we'll simulate with polling
    let intervalId: ReturnType<typeof setInterval>
    
    const poll = async () => {
      try {
        // In a real implementation, this would check for new events
        // For demo purposes, we'll just show the concept
      } catch (error) {
        console.error('Polling error:', error)
      }
    }
    
    if (!signal?.aborted) {
      intervalId = setInterval(poll, 30000) // Poll every 30 seconds
    }
    
    return () => {
      if (intervalId) clearInterval(intervalId)
    }
  }
}
