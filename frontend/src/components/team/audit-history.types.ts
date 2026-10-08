import { type AuditOutcome } from '@/lib/audit'

// Extended audit event with additional fields
export interface AuditEventExtended {
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
  ip_address?: string
  user_agent?: string
  // Additional computed fields
  category?: string
  formatted_date?: string
  relative_time?: string
}

// Enhanced filter options
export interface AuditFiltersExtended {
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
  sort_by?: string
  sort_order?: 'asc' | 'desc'
}

// Filter presets
export type FilterPreset = 'today' | 'last_7_days' | 'last_30_days' | 'last_90_days' | 'custom'

// View modes
export type ViewMode = 'cards' | 'table' | 'timeline'

// Sortable columns
export type SortableColumn = 'created_at' | 'action' | 'actor_username' | 'outcome' | 'tenant_id'

// Statistics for dashboard
export interface AuditStatistics {
  total_events: number
  by_outcome: {
    success: number
    failure: number
  }
  by_action: Record<string, number>
  by_actor: Record<string, number>
  by_date: Record<string, number>
  by_category: Record<string, number>
}

// Export options
export type ExportFormat = 'csv' | 'json'

export interface ExportOptions {
  format: ExportFormat
  include_headers: boolean
  columns: string[]
}

// Chart data
export interface ChartData {
  labels: string[]
  datasets: {
    label: string
    data: number[]
    backgroundColor: string | string[]
    borderColor: string | string[]
  }[]
}

// Real-time update types
export interface RealtimeUpdate {
  type: 'new_event' | 'update_event' | 'delete_event'
  event: AuditEventExtended
  timestamp: string
}

// Complete audit page state
export interface AuditPageState {
  events: AuditEventExtended[]
  total: number
  limit: number
  offset: number
  statistics?: AuditStatistics
}

// Action categories with their labels and colors
export const ACTION_CATEGORIES = {
  authentication: {
    label: 'Authentication',
    actions: ['login', 'first_admin_created', 'admin_password_reset', 'admin_password_reset_via_otp', 'password_changed'],
    color: 'blue'
  },
  accounts: {
    label: 'Admin accounts',
    actions: ['admin_created', 'admin_updated', 'admin_deleted'],
    color: 'green'
  },
  tenant_setup: {
    label: 'Tenant setup',
    actions: [
      'tenant_created', 'tenant_deleted', 'tenant_profile_draft_saved',
      'tenant_intent_draft_saved', 'tenant_profile_published',
      'tenant_profile_rolled_back', 'tenant_phone_id_bound',
      'tenant_webhook_secret_configured', 'tenant_token_created',
      'tenant_token_revoked', 'config_draft_saved', 'config_draft_built', 'config_published'
    ],
    color: 'purple'
  },
  api_access: {
    label: 'API access',
    actions: ['api_access_request_submitted', 'api_access_request_reviewed'],
    color: 'orange'
  }
} as const

// Column definitions for table view
export interface ColumnDefinition {
  key: string
  label: string
  sortable: boolean
  width?: string
  render?: (event: AuditEventExtended) => React.ReactNode
}

export const DEFAULT_COLUMNS: ColumnDefinition[] = [
  { key: 'created_at', label: 'Date/Time', sortable: true, width: '180px' },
  { key: 'action', label: 'Action', sortable: true, width: '200px' },
  { key: 'actor_username', label: 'Actor', sortable: true, width: '150px' },
  { key: 'target_username', label: 'Target', sortable: true, width: '150px' },
  { key: 'tenant_id', label: 'Tenant', sortable: true, width: '120px' },
  { key: 'outcome', label: 'Outcome', sortable: true, width: '100px' },
  { key: 'ip_address', label: 'IP Address', sortable: true, width: '150px' },
  { key: 'resource_type', label: 'Resource Type', sortable: true, width: '150px' },
]

// Filter persistence key
export const FILTER_STORAGE_KEY = 'audit_history_filters'
<<<<<<< HEAD
=======

// Labels for display
export const LABELS = {
  created_at: 'Date/Time',
  action: 'Action',
  actor_username: 'Actor',
  target_username: 'Target',
  tenant_id: 'Tenant',
  outcome: 'Outcome',
  ip_address: 'IP Address',
  resource_type: 'Resource Type',
} as const;
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
