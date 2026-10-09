import { type AuditOutcome } from '@/lib/audit'
import type React from 'react'

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
  tenant_name?: string | null
  tenant_slug?: string | null
  tenant_label?: string
  actor_kind?: string | null
  actor_label?: string | null
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
  menus: {
    label: 'Menus & schema',
    actions: [
      'menu_settings_updated', 'menu_item_updated', 'menu_item_created',
      'menu_item_deleted', 'menu_reordered', 'menu_reset',
      'tenant_profile_draft_saved', 'tenant_intent_draft_saved', 'tenant_profile_published',
      'tenant_profile_rolled_back',
      'record_schema_column_created', 'record_schema_column_updated',
      'record_schema_column_deleted', 'record_schema_reset'
    ],
    color: 'purple'
  },
  products: {
    label: 'Products & services',
    actions: ['product_created', 'product_updated', 'product_deleted', 'product_deleted_hard'],
    color: 'green'
  },
  files: {
    label: 'Files & brochures',
    actions: ['file_uploaded', 'file_deleted', 'brochure_delete', 'brochure_uploaded'],
    color: 'orange'
  },
  operations: {
    label: 'Operations',
    actions: [
      'order_updated', 'order_deleted', 'order_created',
      'campaign_created', 'campaign_updated', 'campaign_deleted',
      'complaint_created', 'complaint_updated', 'complaint_deleted',
      'complaint_resolved', 'complaint_replied',
      'distributor_created', 'distributor_updated', 'distributor_deleted'
    ],
    color: 'orange'
  },
  integrations: {
    label: 'Integrations & API',
    actions: ['integration_configured', 'integration_tested', 'api_access_request_submitted', 'api_access_request_reviewed'],
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
  { key: 'tenant_label', label: 'Tenant / client', sortable: true, width: '220px' },
  { key: 'outcome', label: 'Outcome', sortable: true, width: '100px' },
  { key: 'ip_address', label: 'IP Address', sortable: true, width: '150px' },
  { key: 'user_agent', label: 'User Agent', sortable: false, width: '220px' },
  { key: 'resource_type', label: 'Resource Type', sortable: true, width: '150px' },
  { key: 'resource_id', label: 'Resource ID', sortable: true, width: '150px' },
]

// Filter persistence key
export const FILTER_STORAGE_KEY = 'audit_history_filters'

// Labels for display
export const LABELS = {
  created_at: 'Date/Time',
  action: 'Action',
  actor_username: 'Actor',
  actor_id: 'Actor ID',
  actor_role: 'Actor Role',
  actor_kind: 'Actor Kind',
  actor_label: 'Actor Label',
  target_username: 'Target',
  tenant_id: 'Tenant ID',
  tenant_name: 'Tenant Name',
  tenant_slug: 'Tenant Slug',
  tenant_label: 'Tenant',
  outcome: 'Outcome',
  ip_address: 'IP Address',
  user_agent: 'User Agent',
  resource_type: 'Resource Type',
  resource_id: 'Resource ID',
} as const;
