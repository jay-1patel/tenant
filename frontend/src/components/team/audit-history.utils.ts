import { type AuditEventExtended, type FilterPreset, type ExportFormat } from './audit-history.types'
import { ACTION_CATEGORIES, DEFAULT_COLUMNS } from './audit-history.types'
import { formatDate, relativeTime } from '@/lib/format'

// Action labels mapping
export const LABELS: Record<string, string> = {
  login: 'Login',
  first_admin_created: 'Initial superadmin created',
  admin_created: 'Admin account created',
  admin_updated: 'Admin account updated',
  admin_deleted: 'Admin account deleted',
  admin_password_reset: 'Admin password reset',
  admin_password_reset_via_otp: 'Password reset by recovery',
  password_changed: 'Password changed',
  tenant_created: 'Tenant created',
  tenant_deleted: 'Tenant deleted',
  tenant_profile_draft_saved: 'Tenant profile draft saved',
  tenant_intent_draft_saved: 'Tenant page draft saved',
  tenant_profile_published: 'Tenant profile published',
  tenant_profile_rolled_back: 'Tenant profile rolled back',
  tenant_phone_id_bound: 'Tenant phone ID bound',
  tenant_webhook_secret_configured: 'Tenant webhook secret configured',
  tenant_token_created: 'Tenant token created',
  tenant_token_revoked: 'Tenant token revoked',
  api_access_request_submitted: 'API access request submitted',
  api_access_request_reviewed: 'API access request reviewed',
  config_draft_saved: 'Configuration draft saved',
  config_draft_built: 'Configuration draft generated',
  config_published: 'Configuration published',
  file_uploaded: 'File uploaded',
  file_deleted: 'File deleted',
  product_created: 'Product/service created',
  product_updated: 'Product/service updated',
  product_deleted: 'Product/service deactivated',
  product_deleted_hard: 'Product/service deleted',
  order_updated: 'Order updated',
  order_deleted: 'Order deleted',
  campaign_created: 'Campaign created',
  campaign_updated: 'Campaign updated',
  campaign_deleted: 'Campaign deleted',
  complaint_updated: 'Complaint updated',
  complaint_deleted: 'Complaint deleted',
  complaint_resolved: 'Complaint resolved',
  complaint_replied: 'Complaint replied',
  menu_item_updated: 'Menu option updated',
  menu_item_created: 'Menu option created',
  menu_item_deleted: 'Menu option hidden/deleted',
  menu_reordered: 'Menu reordered',
  menu_settings_updated: 'Menu settings updated',
  menu_reset: 'Menu reset',
  record_schema_column_created: 'Record field created',
  record_schema_column_updated: 'Record field updated',
  record_schema_column_deleted: 'Record field deleted',
  record_schema_reset: 'Record fields reset',
}

// Get category for action
export function getCategoryForAction(action: string): string | undefined {
  for (const [category, config] of Object.entries(ACTION_CATEGORIES)) {
    if (config.actions.includes(action)) {
      return category
    }
  }
  return undefined
}

// Get color for category
export function getCategoryColor(category: string): string {
  const categoryConfig = Object.values(ACTION_CATEGORIES).find(c => c.label === category)
  return categoryConfig?.color || 'slate'
}

// Get color class for category
export function getCategoryColorClass(category: string): string {
  const color = getCategoryColor(category)
  const colorMap: Record<string, string> = {
    blue: 'text-blue-500 bg-blue-500/10',
    green: 'text-green-500 bg-green-500/10',
    purple: 'text-purple-500 bg-purple-500/10',
    orange: 'text-orange-500 bg-orange-500/10',
    slate: 'text-slate-400 bg-slate-500/10'
  }
  return colorMap[color] || colorMap.slate
}

// Format every safe detail key rather than silently dropping unrecognized fields.
export function formatAuditValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (Array.isArray(value)) return value.map(formatAuditValue).join(', ')
  if (typeof value === 'object') {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replace(/_/g, ' ')}: ${formatAuditValue(item)}`)
      .join(' · ')
  }
  return String(value)
}

export function describeDetails(details: Record<string, unknown>): string {
  return Object.entries(details)
    .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${formatAuditValue(value)}`)
    .join(' · ')
}

/* legacy filtered detail summary removed
  if (typeof details.role === 'string') parts.push(`Role: ${details.role}`)
  if (typeof details.role_before === 'string' && typeof details.role_after === 'string' && details.role_before !== details.role_after) {
    parts.push(`Role changed: ${details.role_before} → ${details.role_after}`)
  }
  if (typeof details.version === 'number') parts.push(`Version ${details.version}`)
  if (typeof details.decision === 'string') parts.push(`Decision: ${details.decision}`)
  if (typeof details.api_type === 'string') parts.push(`Type: ${details.api_type}`)
  if (typeof details.scope === 'string') parts.push(`Scope: ${details.scope}`)
  if (Array.isArray(details.changed_sections)) parts.push(`Sections: ${details.changed_sections.join(', ')}`)
  if (Array.isArray(details.changed_fields)) parts.push(`Fields: ${details.changed_fields.join(', ')}`)
  if (Array.isArray(details.permission_keys_changed) && details.permission_keys_changed.length) {
    parts.push(`Permissions changed: ${details.permission_keys_changed.join(', ')}`)
  }
  if (typeof details.configured === 'boolean') parts.push(details.configured ? 'Configured' : 'Not configured')
  if (typeof details.label === 'string' && details.label) parts.push(`Label: ${details.label}`)
  
  return parts.join(' \· ')
}

*/

// Filter preset dates
export function getPresetDates(preset: FilterPreset): { start_date: string; end_date: string } {
  const today = new Date()
  const formatDateStr = (date: Date): string => date.toISOString().split('T')[0]
  
  switch (preset) {
    case 'today': {
      const start = new Date(today)
      start.setHours(0, 0, 0, 0)
      return {
        start_date: formatDateStr(start),
        end_date: formatDateStr(today)
      }
    }
    case 'last_7_days': {
      const start = new Date(today)
      start.setDate(today.getDate() - 6)
      start.setHours(0, 0, 0, 0)
      return {
        start_date: formatDateStr(start),
        end_date: formatDateStr(today)
      }
    }
    case 'last_30_days': {
      const start = new Date(today)
      start.setDate(today.getDate() - 29)
      start.setHours(0, 0, 0, 0)
      return {
        start_date: formatDateStr(start),
        end_date: formatDateStr(today)
      }
    }
    case 'last_90_days': {
      const start = new Date(today)
      start.setDate(today.getDate() - 89)
      start.setHours(0, 0, 0, 0)
      return {
        start_date: formatDateStr(start),
        end_date: formatDateStr(today)
      }
    }
    case 'custom':
    default:
      return { start_date: '', end_date: '' }
  }
}

// Format audit event for display
export function formatEventForDisplay(event: AuditEventExtended): AuditEventExtended {
  return {
    ...event,
    tenant_label: event.tenant_label || [event.tenant_name, event.tenant_slug, event.tenant_id].filter(Boolean).join(' · ') || 'Platform',
    formatted_date: formatDate(event.created_at),
    relative_time: relativeTime(event.created_at),
    category: getCategoryForAction(event.action)
  }
}

// Prepare event data for export
export function prepareExportData(events: AuditEventExtended[], columns: string[]): Record<string, unknown>[] {
  return events.map(event => {
    const formattedEvent = formatEventForDisplay(event)
    const row: Record<string, unknown> = {}
    
    columns.forEach(col => {
      switch (col) {
        case 'created_at':
          row[col] = formattedEvent.formatted_date
          break
        case 'relative_time':
          row[col] = formattedEvent.relative_time
          break
        case 'category':
          row[col] = formattedEvent.category || 'Unknown'
          break
        case 'action':
          row[col] = LABELS[formattedEvent.action] || formattedEvent.action
          break
        case 'outcome':
          row[col] = formattedEvent.outcome
          break
        case 'details':
          row[col] = JSON.stringify(formattedEvent.details || {})
          break
        case 'tenant_label':
          row[col] = formattedEvent.tenant_label || formattedEvent.tenant_name || formattedEvent.tenant_id || 'Platform'
          break
        case 'category_label':
          row[col] = formattedEvent.category ? ACTION_CATEGORIES[formattedEvent.category as keyof typeof ACTION_CATEGORIES]?.label : 'Unknown'
          break
        default:
          row[col] = (formattedEvent as Record<string, unknown>)[col]
      }
    })
    
    return row
  })
}

// Generate CSV content
export function generateCSV(data: Record<string, unknown>[], includeHeaders: boolean = true): string {
  if (data.length === 0) return ''
  
  const headers = Object.keys(data[0])
  const lines: string[] = []
  
  if (includeHeaders) {
    lines.push(headers.map(header => `"${header.replace(/"/g, '""')}"`).join(','))
  }
  
  data.forEach(row => {
    const values = headers.map(header => {
      const value = row[header]
      if (value === null || value === undefined) return ''
      const strValue = String(value).replace(/"/g, '""')
      return `"${strValue}"`
    })
    lines.push(values.join(','))
  })
  
  return lines.join('\n')
}

// Generate JSON content
export function generateJSON(data: Record<string, unknown>[], includeHeaders: boolean = true): string {
  return JSON.stringify(data, null, 2)
}

// Get default columns for export
export function getDefaultExportColumns(): string[] {
  return DEFAULT_COLUMNS.map(col => col.key).concat(['actor_id', 'actor_role', 'actor_kind', 'actor_label', 'category', 'details'])
}

// Save filters to localStorage
export function saveFiltersToStorage(filters: Record<string, unknown>): void {
  try {
    localStorage.setItem('audit_history_filters', JSON.stringify(filters))
  } catch (error) {
    console.error('Failed to save filters to localStorage:', error)
  }
}

// Load filters from localStorage
export function loadFiltersFromStorage(): Record<string, unknown> | null {
  try {
    const saved = localStorage.getItem('audit_history_filters')
    if (saved) {
      return JSON.parse(saved)
    }
  } catch (error) {
    console.error('Failed to load filters from localStorage:', error)
  }
  return null
}

// Debounce function for search input
export function debounce<T extends (...args: Parameters<T>) => ReturnType<T>>(
  func: T,
  wait: number
): (...args: Parameters<T>) => void {
  let timeout: ReturnType<typeof setTimeout>
  
  return function(...args: Parameters<T>): void {
    clearTimeout(timeout)
    timeout = setTimeout(() => func(...args), wait)
  }
}

// Get outcome color class
export function getOutcomeColorClass(outcome: string): string {
  switch (outcome) {
    case 'success':
      return 'text-green-500 bg-green-500/10'
    case 'failure':
      return 'text-red-500 bg-red-500/10'
    default:
      return 'text-slate-400 bg-slate-500/10'
  }
}

// Get trend indicator based on comparison
export function getTrendIndicator(current: number, previous: number): 'increase' | 'decrease' | 'stable' {
  if (current > previous) return 'increase'
  if (current < previous) return 'decrease'
  return 'stable'
}
