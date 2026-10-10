import React, { useState, useMemo, useEffect, useCallback } from 'react'
import { useAsync } from '@/lib/hooks'
import { formatDate, relativeTime } from '@/lib/format'
import { auditApiExtended } from '@/lib/audit.extended'
import { Card, CardHeader, CardBody } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock, Toast } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { ChevronLeft, ChevronRight, RefreshCw, Table2, Grid3X3, LineChart, Filter, Download, X } from 'lucide-react'
import type { AuditEventExtended, AuditFiltersExtended, AuditPageState, ViewMode, FilterPreset, AuditStatistics, AuditOutcome } from './audit-history.types'
import { LABELS, ACTION_CATEGORIES, getPresetDates, formatEventForDisplay, debounce, saveFiltersToStorage, loadFiltersFromStorage, prepareExportData, generateCSV, generateJSON, getDefaultExportColumns } from './audit-history.utils'

const PAGE_SIZE = 50

// Filter Presets Component
const FilterPresets = ({ onApplyPreset }: { onApplyPreset: (preset: Record<string, unknown>) => void }) => {
  const [isOpen, setIsOpen] = useState(false)

  const presets = [
    { name: 'Today', filters: getPresetDates('today') },
    { name: 'Last 7 days', filters: getPresetDates('last_7_days') },
    { name: 'Last 30 days', filters: getPresetDates('last_30_days') },
    { name: 'Last 90 days', filters: getPresetDates('last_90_days') },
    { name: 'All time', filters: {} },
    { name: 'Successful only', filters: { outcome: 'success' } },
    { name: 'Failed only', filters: { outcome: 'failure' } },
  ]

  return (
    <div className="relative">
      <Button variant="secondary" size="sm" onClick={() => setIsOpen(!isOpen)}>
        <Filter className="h-4 w-4" />
        Presets
      </Button>
      {isOpen && (
        <div className="absolute right-0 z-50 mt-2 w-48 rounded-lg bg-surface-overlay shadow-lg ring-1 ring-surface-line">
          <div className="py-1">
            {presets.map((preset) => (
              <button
                key={preset.name}
                onClick={() => {
                  onApplyPreset({ ...preset.filters, preset: preset.name.toLowerCase().replace(/\s+/g, '_') })
                  setIsOpen(false)
                }}
                className="block w-full px-4 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
              >
                {preset.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// Export Menu Component
const ExportMenu = ({ events, filters, onExportSuccess }: { events: AuditEventExtended[]; filters: AuditFiltersExtended; onExportSuccess: () => void }) => {
  const [isOpen, setIsOpen] = useState(false)
  const [isExporting, setIsExporting] = useState(false)

  const handleExport = async (format: 'csv' | 'json') => {
    setIsExporting(true)
    try {
      const columns = getDefaultExportColumns()
      const request = { filters, format, columns }
      const response = await auditApiExtended.exportEvents(request)
      
      // Create download link
      const url = window.URL.createObjectURL(new Blob([response]))
      const link = document.createElement('a')
      link.href = url
      link.download = `audit-history-${new Date().toISOString().split('T')[0]}.${format}`
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      window.URL.revokeObjectURL(url)
      
      onExportSuccess()
    } catch (error) {
      console.error('Export failed:', error)
    } finally {
      setIsExporting(false)
      setIsOpen(false)
    }
  }

  return (
    <div className="relative">
      <Button variant="secondary" size="sm" onClick={() => setIsOpen(!isOpen)} disabled={isExporting || events.length === 0}>
        <Download className="h-4 w-4" />
        Export
      </Button>
      {isOpen && (
        <div className="absolute right-0 z-50 mt-2 w-40 rounded-lg bg-surface-overlay shadow-lg ring-1 ring-surface-line p-2">
          <button
            onClick={() => handleExport('csv')}
            className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            Export as CSV
          </button>
          <button
            onClick={() => handleExport('json')}
            className="block w-full px-3 py-2 text-left text-sm text-slate-700 hover:bg-slate-50"
          >
            Export as JSON
          </button>
        </div>
      )}
    </div>
  )
}

// Date Range Picker Component
const DateRangePicker = ({ startDate, endDate, preset, onChange }: { startDate: string; endDate: string; preset: FilterPreset; onChange: (preset: FilterPreset, startDate: string, endDate: string) => void }) => {
  const handlePresetChange = (newPreset: FilterPreset) => {
    const dates = getPresetDates(newPreset)
    onChange(newPreset, dates.start_date, dates.end_date)
  }

  return (
    <div className="flex flex-wrap gap-1">
      {(['today', 'last_7_days', 'last_30_days', 'last_90_days'] as FilterPreset[]).map((p) => (
        <Button
          key={p}
          size="sm"
          variant={preset === p ? 'primary' : 'secondary'}
          onClick={() => handlePresetChange(p)}
        >
          {p.replace(/_/g, ' ')}
        </Button>
      ))}
      {preset === 'custom' && (
        <div className="flex gap-2">
          <Input type="date" value={startDate} onChange={(e) => onChange('custom', e.target.value, endDate)} />
          <Input type="date" value={endDate} onChange={(e) => onChange('custom', startDate, e.target.value)} />
        </div>
      )}
    </div>
  )
}

// Audit Event Details Component
const AuditEventDetails = ({ event }: { event: AuditEventExtended }) => {
  const details = event.details || {}
  
  // Format detail values for display
  const formatDetailValue = (value: unknown): string => {
    if (value === null || value === undefined || value === '') return '—'
    if (typeof value === 'boolean') return value ? 'Yes' : 'No'
    if (Array.isArray(value)) return value.map(formatDetailValue).join(', ')
    if (typeof value === 'object') {
      return Object.entries(value as Record<string, unknown>)
        .map(([key, val]) => `${key.replace(/_/g, ' ')}: ${formatDetailValue(val)}`)
        .join(' | ')
    }
    return String(value)
  }

  // Check for specific detail fields to highlight
  const getHighlightedDetails = () => {
    const parts: string[] = []
    
    if (details.name || details.title) {
      parts.push(`Name: ${details.name || details.title}`)
    }
    if (details.description) {
      parts.push(`Description: ${details.description}`)
    }
    if (details.role) {
      parts.push(`Role: ${details.role}`)
    }
    if (details.role_before && details.role_after) {
      parts.push(`Role changed: ${details.role_before} → ${details.role_after}`)
    }
    if (details.version) {
      parts.push(`Version: ${details.version}`)
    }
    if (details.decision) {
      parts.push(`Decision: ${details.decision}`)
    }
    if (details.api_type) {
      parts.push(`API Type: ${details.api_type}`)
    }
    if (details.scope) {
      parts.push(`Scope: ${details.scope}`)
    }
    if (Array.isArray(details.changed_fields) && details.changed_fields.length > 0) {
      parts.push(`Fields: ${details.changed_fields.join(', ')}`)
    }
    if (Array.isArray(details.changed_sections) && details.changed_sections.length > 0) {
      parts.push(`Sections: ${details.changed_sections.join(', ')}`)
    }
    if (Array.isArray(details.permission_keys_changed) && details.permission_keys_changed.length > 0) {
      parts.push(`Permissions: ${details.permission_keys_changed.join(', ')}`)
    }
    if (typeof details.configured === 'boolean') {
      parts.push(details.configured ? 'Configured' : 'Not configured')
    }
    if (details.label) {
      parts.push(`Label: ${details.label}`)
    }
    
    // Fallback: show all details if no specific ones matched
    if (parts.length === 0 && Object.keys(details).length > 0) {
      return Object.entries(details)
        .map(([key, value]) => `${key.replace(/_/g, ' ')}: ${formatDetailValue(value)}`)
        .join(' | ')
    }
    
    return parts.join(' | ') || 'No additional details'
  }

  return (
    <div className="text-sm text-slate-400">
      {getHighlightedDetails()}
    </div>
  )
}

// Table View Component
const TableView = ({ events, sortBy, sortOrder, onSort }: { events: AuditEventExtended[]; sortBy: string; sortOrder: 'asc' | 'desc'; onSort: (column: string) => void }) => {
  const getSortIcon = (column: string) => {
    if (sortBy !== column) return null
    return sortOrder === 'asc' ? '↑' : '↓'
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-surface-panel">
          <tr>
            <th onClick={() => onSort('created_at')} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-pointer hover:bg-surface-panel">
              Date/Time {getSortIcon('created_at')}
            </th>
            <th onClick={() => onSort('action')} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-pointer hover:bg-surface-panel">
              Action {getSortIcon('action')}
            </th>
            <th onClick={() => onSort('actor_username')} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-pointer hover:bg-surface-panel">
              Actor {getSortIcon('actor_username')}
            </th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300">
              Target
            </th>
            <th onClick={() => onSort('tenant_label')} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-pointer hover:bg-surface-panel">
              Tenant {getSortIcon('tenant_label')}
            </th>
            <th onClick={() => onSort('outcome')} className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-300 cursor-pointer hover:bg-surface-panel">
              Outcome {getSortIcon('outcome')}
            </th>
          </tr>
        </thead>
        <tbody className="bg-surface-raised divide-y divide-surface-line">
          {events.map((event) => {
            const formattedEvent = formatEventForDisplay(event)
            return (
              <tr key={event.id} className="hover:bg-surface-panel">
                <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-200">
                  {formattedEvent.formatted_date}
                  <div className="text-xs text-slate-500">{formattedEvent.relative_time}</div>
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-200">
                  {LABELS[event.action] || event.action.replace(/_/g, ' ')}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-200">
                  {event.actor_label || event.actor_username || 'System'}
                  {event.actor_role && <div className="text-xs text-slate-500">{event.actor_role}</div>}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-200">
                  {event.target_username || '—'}
                </td>
                <td className="px-4 py-3 whitespace-nowrap text-sm text-slate-200">
                  {formattedEvent.tenant_label}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">
                  <Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>
                    {event.outcome}
                  </Badge>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Statistics View Component
const StatisticsView = ({ statistics, events }: { statistics: AuditStatistics; events: AuditEventExtended[] }) => {
  return (
    <Card className="mb-4">
      <CardHeader title="Audit Statistics" />
      <CardBody>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-200">{statistics.total_events.toLocaleString()}</div>
            <div className="text-sm text-slate-500">Total Events</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-emerald-600">{statistics.by_outcome.success.toLocaleString()}</div>
            <div className="text-sm text-slate-500">Success</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-rose-600">{statistics.by_outcome.failure.toLocaleString()}</div>
            <div className="text-sm text-slate-500">Failures</div>
          </div>
          <div className="text-center">
            <div className="text-2xl font-bold text-slate-200">{Object.keys(statistics.by_actor || {}).length}</div>
            <div className="text-sm text-slate-500">Unique Actors</div>
          </div>
        </div>
        {events.length > 0 && (
          <div className="mt-4 pt-4 border-t border-surface-line">
            <h4 className="text-sm font-semibold text-slate-300 mb-2">Top Actions</h4>
            <div className="flex flex-wrap gap-2">
              {Object.entries(statistics.by_action || {})
                .sort(([, a], [, b]) => (b as number) - (a as number))
                .slice(0, 5)
                .map(([action, count]) => (
                  <Badge key={action} tone="neutral">
                    {LABELS[action as keyof typeof LABELS] || action.replace(/_/g, ' ')}: {count}
                  </Badge>
                ))}
            </div>
          </div>
        )}
      </CardBody>
    </Card>
  )
}

// Timeline View Component
const TimelineView = ({ events }: { events: AuditEventExtended[] }) => {
  const eventsByDate = useMemo(() => {
    const grouped: Record<string, AuditEventExtended[]> = {}
    events.forEach(event => {
      const date = new Date(event.created_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
      ;(grouped[date] ??= []).push(event)
    })
    return grouped
  }, [events])

  return (
    <div className="space-y-8">
      {Object.entries(eventsByDate).map(([date, dateEvents]) => (
        <section key={date} className="space-y-3">
          <h3 className="text-lg font-semibold text-slate-200">
            {date} <span className="text-xs font-normal text-slate-500">{dateEvents.length} events</span>
          </h3>
          <div className="space-y-3 border-l border-surface-line pl-4">
            {dateEvents.map(event => {
              const formattedEvent = formatEventForDisplay(event)
              return (
                <Card key={event.id} className="bg-surface-panel border-surface-line">
                  <CardHeader 
                    title={LABELS[event.action] || event.action.replace(/_/g, ' ')} 
                    description={`${event.actor_label || event.actor_username || 'System'}${event.actor_role ? ` · ${event.actor_role}` : ''} · ${relativeTime(event.created_at)}`} 
                    actions={<Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>}
                  />
                  <CardBody className="space-y-3">
                    <div className="flex flex-wrap gap-3 text-xs text-slate-400">
                      <span>Tenant: {formattedEvent.tenant_label || event.tenant_name || event.tenant_id || 'Platform'}{event.tenant_slug ? ` · ${event.tenant_slug}` : ''}</span>
                      <span>IP: {event.ip_address || '—'}</span>
                      <span>Resource: {event.resource_type || '—'}{event.resource_id ? `/${event.resource_id}` : ''}</span>
                    </div>
                    <AuditEventDetails event={event} />
                  </CardBody>
                </Card>
              )
            })}
          </div>
        </section>
      ))}
    </div>
  )
}

// Main AuditHistory Component
export function AuditHistory() {
  const [filters, setFilters] = useState<AuditFiltersExtended>({ 
    limit: PAGE_SIZE, 
    offset: 0, 
    sort_by: 'created_at', 
    sort_order: 'desc' 
  })
  const [draft, setDraft] = useState({
    search: '',
    actor: '',
    action: '',
    category: '',
    tenant_id: '',
    outcome: '' as AuditOutcome | '',
    start_date: '',
    end_date: '',
    preset: 'last_7_days' as FilterPreset,
  })
  const [viewMode, setViewMode] = useState<ViewMode>('table')
  const [selectedEvents, setSelectedEvents] = useState<Set<number>>(new Set())
  const [showRefreshing, setShowRefreshing] = useState(false)
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [showCustomDateRange, setShowCustomDateRange] = useState(false)

  // Load saved filters from localStorage
  useEffect(() => {
    const savedFilters = loadFiltersFromStorage()
    if (savedFilters) {
      setDraft(prev => ({ ...prev, ...savedFilters }))
      // Apply saved date preset
      if (savedFilters.preset) {
        const dates = getPresetDates(savedFilters.preset as FilterPreset)
        setDraft(prev => ({ ...prev, ...dates, preset: savedFilters.preset }))
      }
    }
  }, [])

  const requestFilters = useMemo(() => ({
    ...filters, 
    limit: filters.limit ?? PAGE_SIZE,
    start_date: draft.start_date || undefined,
    end_date: draft.end_date || undefined,
    actor: draft.actor || filters.actor,
    action: draft.action || filters.action,
    category: draft.category || filters.category,
    tenant_id: draft.tenant_id || filters.tenant_id,
    outcome: draft.outcome || filters.outcome,
    search: draft.search || filters.search,
  }), [filters, draft])

  // Fetch audit data
  const state = useAsync(() => auditApiExtended.list(requestFilters) as Promise<AuditPageState>, [JSON.stringify(requestFilters)])
  const page = state.data
  const events = page?.events ?? []
  const formattedEvents = useMemo(() => events.map(formatEventForDisplay), [events])

  // Fetch statistics
  const statistics = useAsync(() => 
    auditApiExtended.getStatistics(filters) as Promise<AuditStatistics>, 
    [JSON.stringify(filters)]
  )

  const start = page && page.total ? page.offset + 1 : 0
  const end = page ? page.offset + page.events.length : 0

  // Apply filters
  const applyFilters = useCallback((nextDraft = draft) => {
    const next: AuditFiltersExtended = {
      start_date: nextDraft.start_date || undefined,
      end_date: nextDraft.end_date || undefined,
      actor: nextDraft.actor || undefined,
      action: nextDraft.action || undefined,
      category: nextDraft.category || undefined,
      tenant_id: nextDraft.tenant_id || undefined,
      outcome: nextDraft.outcome || undefined,
      search: nextDraft.search || undefined,
      limit: PAGE_SIZE,
      offset: 0,
      sort_by: filters.sort_by,
      sort_order: filters.sort_order,
    }
    setFilters(next)
    saveFiltersToStorage(nextDraft)
  }, [draft, filters.sort_by, filters.sort_order])

  // Debounced search
  const debouncedSearch = useMemo(() => debounce((value: string) => {
    setDraft(prev => ({ ...prev, search: value }))
    applyFilters({ ...draft, search: value })
  }, 300), [applyFilters, draft])

  const handleSort = (column: string) => {
    setFilters(current => ({
      ...current,
      sort_by: column || 'created_at',
      sort_order: current.sort_by === column && current.sort_order === 'desc' ? 'asc' : 'desc',
      offset: 0,
    }))
  }

  const updateDraft = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => {
    setDraft(current => ({ ...current, [key]: value }))
  }

  const clearFilters = () => {
    const clean = { 
      search: '', 
      actor: '', 
      action: '', 
      category: '', 
      tenant_id: '', 
      outcome: '' as AuditOutcome | '', 
      start_date: '', 
      end_date: '', 
      preset: 'last_7_days' as FilterPreset 
    }
    setDraft(clean)
    setFilters({ limit: PAGE_SIZE, offset: 0, sort_by: 'created_at', sort_order: 'desc' })
    saveFiltersToStorage(clean)
  }

  const refresh = () => {
    setShowRefreshing(true)
    void state.reload().finally(() => setTimeout(() => setShowRefreshing(false), 600))
  }

  const notifyExport = () => {
    setToastMessage('Audit export downloaded')
    setTimeout(() => setToastMessage(null), 2500)
  }

  const applyPreset = (preset: Record<string, unknown>) => {
    const next = { ...draft, ...preset } as typeof draft
    setDraft(next)
    applyFilters(next)
  }

  return (
    <div className="space-y-4">
      <PageHeader 
        title="Audit History" 
        description="Review administrator activity across tenants, with actor, client, request and change details."
        actions={
          <div className="flex flex-wrap gap-2">
            <FilterPresets onApplyPreset={applyPreset} />
            <ExportMenu events={formattedEvents} filters={filters} onExportSuccess={notifyExport} />
            <Button 
              variant="secondary" 
              icon={<RefreshCw className={`h-4 w-4 ${showRefreshing ? 'animate-spin' : ''}`} />}
              onClick={refresh}
              disabled={state.loading}
            >
              Refresh
            </Button>
          </div>
        }
      />
      
      {toastMessage && <Toast>{toastMessage}</Toast>}
      {state.error && <Alert tone="danger" title="Could not load audit history">{String(state.error)}</Alert>}
      {state.loading && <LoadingBlock label="Loading audit history..." />}

      {/* Filter Card */}
      <Card>
        <CardHeader 
          title="Filters" 
          description="Search actors, clients, IP addresses, user agents and safe event details."
          actions={
            <Button size="sm" variant="ghost" onClick={() => setShowAdvancedFilters(v => !v)}>
              {showAdvancedFilters ? 'Hide' : 'More'} filters
            </Button>
          }
        />
        <CardBody className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Input 
              label="Search" 
              placeholder="Filename, IP, actor, change..." 
              value={draft.search} 
              onChange={e => { 
                updateDraft('search', e.target.value); 
                debouncedSearch(e.target.value) 
              }} 
            />
            <Input 
              label="Actor" 
              placeholder="Username" 
              value={draft.actor} 
              onChange={e => updateDraft('actor', e.target.value)} 
            />
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Action</label>
              <Select 
                value={draft.action} 
                onChange={e => updateDraft('action', e.target.value)}
                className="w-full"
              >
                <option value="">All actions</option>
                {Object.entries(LABELS).map(([action, label]) => (
                  <option key={action} value={action}>{label}</option>
                ))}
              </Select>
            </div>
            <div>
              <label className="block text-sm font-medium text-slate-300 mb-1">Outcome</label>
              <Select 
                value={draft.outcome} 
                onChange={e => updateDraft('outcome', e.target.value as AuditOutcome | '')}
                className="w-full"
              >
                <option value="">All outcomes</option>
                <option value="success">Success</option>
                <option value="failure">Failure</option>
              </Select>
            </div>
          </div>
          
          {showAdvancedFilters && (
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-1">Category</label>
                <Select 
                  value={draft.category} 
                  onChange={e => updateDraft('category', e.target.value)}
                  className="w-full"
                >
                  <option value="">All categories</option>
                  {Object.entries(ACTION_CATEGORIES).map(([key, value]) => (
                    <option key={key} value={key}>{value.label}</option>
                  ))}
                </Select>
              </div>
              <Input 
                label="Tenant / client ID" 
                placeholder="Tenant ID" 
                value={draft.tenant_id} 
                onChange={e => updateDraft('tenant_id', e.target.value)} 
              />
              <div className="flex items-end gap-2">
                <DateRangePicker
                  startDate={draft.start_date}
                  endDate={draft.end_date}
                  preset={draft.preset}
                  onChange={(preset, start_date, end_date) => {
                    setDraft(current => ({ ...current, preset, start_date, end_date }))
                  }}
                />
              </div>
              <div className="flex items-end gap-2">
                <Button variant="primary" onClick={() => applyFilters()}>
                  Apply filters
                </Button>
                <Button variant="ghost" onClick={clearFilters}>
                  <X className="h-4 w-4" /> Clear
                </Button>
              </div>
            </div>
          )}
          
          {!showAdvancedFilters && (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs text-slate-500">Date range</span>
              {(['today', 'last_7_days', 'last_30_days', 'last_90_days'] as FilterPreset[]).map(preset => (
                <Button 
                  key={preset} 
                  size="sm" 
                  variant={draft.preset === preset ? 'primary' : 'secondary'} 
                  onClick={() => { 
                    const dates = getPresetDates(preset)
                    const next = { ...draft, preset, ...dates }
                    setDraft(next)
                    applyFilters(next)
                  }}
                >
                  {preset.replace(/_/g, ' ')}
                </Button>
              ))}
            </div>
          )}
        </CardBody>
      </Card>

      {/* View Mode Toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Button 
            size="sm" 
            variant={viewMode === 'table' ? 'primary' : 'secondary'} 
            icon={<Table2 className="h-4 w-4" />} 
            onClick={() => setViewMode('table')}
          >
            Table
          </Button>
          <Button 
            size="sm" 
            variant={viewMode === 'cards' ? 'primary' : 'secondary'} 
            icon={<Grid3X3 className="h-4 w-4" />} 
            onClick={() => setViewMode('cards')}
          >
            Cards
          </Button>
          <Button 
            size="sm" 
            variant={viewMode === 'timeline' ? 'primary' : 'secondary'} 
            icon={<LineChart className="h-4 w-4" />} 
            onClick={() => setViewMode('timeline')}
          >
            Timeline
          </Button>
        </div>
        <Button size="sm" variant="ghost" onClick={() => setShowStats(v => !v)}>
          {showStats ? 'Hide' : 'Show'} summary
        </Button>
      </div>

      {/* Statistics Summary */}
      {showStats && statistics.data && (
        <StatisticsView statistics={statistics.data} events={formattedEvents} />
      )}

      {/* Empty State */}
      {page?.events.length === 0 && !state.loading && (
        <Card>
          <CardBody>
            <EmptyState title="No activity found" description="Try changing the filters or date range." />
          </CardBody>
        </Card>
      )}

      {/* Results */}
      {page && page.events.length > 0 && (
        <>
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span>Showing {start}–{end} of {page.total.toLocaleString()} events</span>
            <span>Sort: {filters.sort_by || 'Date'} ({filters.sort_order})</span>
          </div>
          
          {viewMode === 'table' && (
            <TableView 
              events={formattedEvents} 
              sortBy={filters.sort_by || ''} 
              sortOrder={filters.sort_order || 'desc'} 
              onSort={handleSort} 
            />
          )}

          {viewMode === 'cards' && (
            <div className="space-y-3">
              {formattedEvents.map(event => {
                return (
                  <Card key={event.id} className="bg-surface-panel border-surface-line">
                    <CardHeader 
                      title={LABELS[event.action] || event.action.replace(/_/g, ' ')} 
                      description={`${event.actor_label || event.actor_username || 'System'}${event.actor_role ? ` · ${event.actor_role}` : ''} · ${formatDate(event.created_at)}`}
                      actions={<Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>}
                    />
                    <CardBody>
                      <AuditEventDetails event={event} />
                    </CardBody>
                  </Card>
                )
              })}
            </div>
          )}

          {viewMode === 'timeline' && <TimelineView events={formattedEvents} />}

          {/* Pagination */}
          <div className="mt-4 flex items-center justify-between">
            <Button 
              variant="secondary" 
              disabled={page.offset === 0 || state.loading} 
              icon={<ChevronLeft className="h-4 w-4" />} 
              onClick={() => setFilters(v => ({ ...v, offset: Math.max(0, (v.offset ?? 0) - PAGE_SIZE) }))}
            >
              Previous
            </Button>
            <span className="text-xs text-slate-500">
              Page {Math.floor(page.offset / page.limit) + 1} of {Math.max(1, Math.ceil(page.total / page.limit))}
            </span>
            <Button 
              variant="secondary" 
              disabled={page.offset + page.events.length >= page.total || state.loading} 
              icon={<ChevronRight className="h-4 w-4" />} 
              onClick={() => setFilters(v => ({ ...v, offset: (v.offset ?? 0) + PAGE_SIZE }))}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

export type { ViewMode, FilterPreset } from './audit-history.types'

export default AuditHistory
