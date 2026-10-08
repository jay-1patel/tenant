import { useState, useEffect, useCallback, useMemo } from 'react'
import { 
  Search, ChevronLeft, ChevronRight, ChevronDown, ChevronUp, 
  Download, Table2, Grid3X3, TrendingUp, TrendingDown, 
  Calendar, Filter, X, RefreshCw, LineChart
} from 'lucide-react'
import { auditApiExtended } from '@/lib/audit.extended'
import { type AuditEventExtended, type AuditFiltersExtended, type ViewMode, type FilterPreset } from './audit-history.types'
import { 
  formatEventForDisplay, describeDetails, getPresetDates, 
  saveFiltersToStorage, loadFiltersFromStorage, debounce,
  getOutcomeColorClass, getCategoryColorClass, getTrendIndicator,
  generateCSV, generateJSON, getDefaultExportColumns, prepareExportData
} from './audit-history.utils'
import { LABELS, ACTION_CATEGORIES, FILTER_STORAGE_KEY, DEFAULT_COLUMNS } from './audit-history.types'
import { useAsync } from '@/lib/hooks'
import { formatDate, relativeTime } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock, Toast } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { Switch } from '@/components/ui/switch' 

const PAGE_SIZE = 50

//Date Range Picker Component
const DateRangePicker = ({ 
  startDate, 
  endDate, 
  onChange, 
  preset 
}: { 
  startDate: string 
  endDate: string 
  onChange: (preset: FilterPreset, startDate?: string, endDate?: string) => void 
  preset: FilterPreset 
}) => {
  const presets: FilterPreset[] = ['today', 'last_7_days', 'last_30_days', 'last_90_days']
  
  return (
    <div className="space-y-2">
      <label className="block text-sm font-medium text-slate-300">Date Range</label>
      <div className="flex flex-wrap gap-2">
        {presets.map(p => (
          <Button
            key={p}
            variant={preset === p ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => {
              const dates = getPresetDates(p)
              onChange(p, dates.start_date, dates.end_date)
            }}
          >
            {p.replace('_', ' ')}
          </Button>
        ))}
      </div>
      <Button
        variant={preset === 'custom' ? 'primary' : 'secondary'}
        size="sm"
        onClick={() => onChange('custom', '', '')}
      >
        Custom Range
      </Button>
      {preset === 'custom' && (
        <div className="grid grid-cols-2 gap-2 mt-2">
          <Input 
            type="date" 
            value={startDate} 
            onChange={(e) => onChange('custom', e.target.value, endDate)}
            placeholder="From" 
          />
          <Input 
            type="date" 
            value={endDate} 
            onChange={(e) => onChange('custom', startDate, e.target.value)}
            placeholder="To" 
          />
        </div>
      )}
    </div>
  )
}

//Filter Presets Dropdown
const FilterPresets = ({ onApplyPreset }: { onApplyPreset: (preset: Record<string, unknown>) => void }) => {
  const [isOpen, setIsOpen] = useState(false)
  
  const presets = [
    { name: 'Recent Logins', filters: { action: 'login', limit: 100 } },
    { name: 'Failed Events', filters: { outcome: 'failure' } },
    { name: 'Tenant Changes', filters: { category: 'tenant_setup' } },
    { name: 'Admin Actions', filters: { category: 'accounts' } },
    { name: 'API Access', filters: { category: 'api_access' } }
  ]
  
  return (
    <div className="relative">
      <Button 
        variant="secondary" 
        size="sm" 
        icon={<Filter className="h-4 w-4" />}
        onClick={() => setIsOpen(!isOpen)}
      >
        Presets
        <ChevronDown className="h-4 w-4 ml-1" />
      </Button>
      {isOpen && (
        <div className="absolute right-0 mt-2 w-48 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 z-50">
          <div className="py-1">
            {presets.map((preset, index) => (
              <button
                key={index}
                className="block px-4 py-2 text-sm text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 w-full text-left"
                onClick={() => {
                  onApplyPreset(preset.filters)
                  setIsOpen(false)
                }}
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

//Export Options Component
const ExportMenu = ({ 
  events, 
  filters, 
  onExportSuccess 
}: { 
  events: AuditEventExtended[] 
  filters: AuditFiltersExtended 
  onExportSuccess: () => void 
}) => {
  const [isOpen, setIsOpen] = useState(false)
  const [selectedFormat, setSelectedFormat] = useState<'csv' | 'json'>('csv')
  const [selectedColumns, setSelectedColumns] = useState<string[]>(getDefaultExportColumns())
  const [isExporting, setIsExporting] = useState(false)
  
  const allColumns = useMemo(() => [
    ...DEFAULT_COLUMNS.map(col => col.key),
    'category', 'details', 'relative_time'
  ], [])
  
  const handleExport = async () => {
    if (events.length === 0) return
    
    setIsExporting(true)
    try {
      // Prepare data for export
      const exportData = prepareExportData(events, selectedColumns)
      
      let content: string
      let mimeType: string
      let filename: string
      
      if (selectedFormat === 'csv') {
        content = generateCSV(exportData)
        mimeType = 'text/csv'
        filename = `audit-history-${new Date().toISOString().split('T')[0]}.csv`
      } else {
        content = generateJSON(exportData)
        mimeType = 'application/json'
        filename = `audit-history-${new Date().toISOString().split('T')[0]}.json`
      }
      
      // Create and download file
      const blob = new Blob([content], { type: mimeType })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
      
      onExportSuccess()
      setIsOpen(false)
    } catch (error) {
      console.error('Export failed:', error)
    } finally {
      setIsExporting(false)
    }
  }
  
  const toggleColumn = (column: string) => {
    setSelectedColumns(prev => 
      prev.includes(column) 
        ? prev.filter(c => c !== column) 
        : [...prev, column]
    )
  }
  
  return (
    <div className="relative">
      <Button 
        variant="secondary" 
        icon={<Download className="h-4 w-4" />}
        disabled={events.length === 0}
        onClick={() => setIsOpen(!isOpen)}
        loading={isExporting}
      >
        Export
        <ChevronDown className="h-4 w-4 ml-1" />
      </Button>
      
      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 bg-white dark:bg-slate-800 rounded-lg shadow-lg border border-slate-200 dark:border-slate-700 z-50 p-4">
          <h3 className="font-semibold text-slate-900 dark:text-slate-100 mb-3">Export Options</h3>
          
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">Format</label>
            <div className="flex gap-2">
              <Button 
                variant={selectedFormat === 'csv' ? 'primary' : 'secondary'} 
                size="sm" 
                onClick={() => setSelectedFormat('csv')}
                className="flex-1"
              >
                CSV
              </Button>
              <Button 
                variant={selectedFormat === 'json' ? 'primary' : 'secondary'} 
                size="sm" 
                onClick={() => setSelectedFormat('json')}
                className="flex-1"
              >
                JSON
              </Button>
            </div>
          </div>
          
          <div className="mb-4">
            <label className="block text-sm font-medium text-slate-600 dark:text-slate-400 mb-2">Columns to Include</label>
            <div className="max-h-40 overflow-y-auto border border-slate-200 dark:border-slate-700 rounded-lg p-2">
              {allColumns.map(column => {
                const isSelected = selectedColumns.includes(column)
                const columnLabel = LABELS[column] || column.replace(/_/g, ' ')
                return (
                  <label key={column} className="flex items-center gap-2 p-1 hover:bg-slate-100 dark:hover:bg-slate-700 rounded cursor-pointer">
                    <input 
                      type="checkbox" 
                      checked={isSelected} 
                      onChange={() => toggleColumn(column)} 
                      className="rounded border-slate-300 dark:border-slate-600 text-accent-600 focus:ring-accent-500"
                    />
                    <span className="text-sm text-slate-600 dark:text-slate-400">{columnLabel}</span>
                  </label>
                )
              })}
            </div>
          </div>
          
          <Button 
            variant="primary" 
            className="w-full" 
            onClick={handleExport}
            disabled={selectedColumns.length === 0}
          >
            {isExporting ? 'Exporting...' : `Export ${events.length} events`}
          </Button>
        </div>
      )}
    </div>
  )
}

//View Toggle Component
const ViewToggle = ({ 
  viewMode, 
  onViewChange 
}: { 
  viewMode: ViewMode 
  onViewChange: (mode: ViewMode) => void 
}) => {
  const views: { mode: ViewMode; label: string; icon: React.ReactNode }[] = [
    { mode: 'cards', label: 'Cards', icon: <Grid3X3 className="h-4 w-4" /> },
    { mode: 'table', label: 'Table', icon: <Table2 className="h-4 w-4" /> },
    { mode: 'timeline', label: 'Timeline', icon: <LineChart className="h-4 w-4" /> }
  ]
  
  return (
    <div className="flex bg-slate-800 rounded-lg p-1">
      {views.map(({ mode, label, icon }) => (
        <button
          key={mode}
          className={`flex items-center gap-2 px-3 py-2 rounded-md text-sm font-medium transition-colors ${
            viewMode === mode 
              ? 'bg-white text-slate-900 shadow' 
              : 'text-slate-400 hover:bg-slate-700 hover:text-white'
          }`}
          onClick={() => onViewChange(mode)}
        >
          {icon}
          {label}
        </button>
      ))}
    </div>
  )
}

//Statistics Dashboard Component
const StatisticsDashboard = ({ 
  statistics, 
  loading 
}: { 
  statistics?: any 
  loading: boolean 
}) => {
  if (loading) return <LoadingBlock label="Loading statistics..." />
  
  if (!statistics) return null
  
  const totalEvents = statistics.total_events || 0
  const successEvents = statistics.by_outcome?.success || 0
  const failureEvents = statistics.by_outcome?.failure || 0
  
  const topActions = Object.entries(statistics.by_action || {})
    .sort(([,a], [,b]) => b - a)
    .slice(0, 5)
  
  const topActors = Object.entries(statistics.by_actor || {})
    .sort(([,a], [,b]) => b - a)
    .slice(0, 5)
  
  return (
    <div className="grid gap-4 mb-6">
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardBody className="text-center">
            <div className="text-3xl font-bold text-slate-100">{totalEvents.toLocaleString()}</div>
            <div className="text-sm text-slate-400">Total Events</div>
          </CardBody>
        </Card>
        
        <Card>
          <CardBody className="flex items-center justify-center gap-4">
            <div className="text-center">
              <div className="text-2xl font-bold text-green-400">{successEvents.toLocaleString()}</div>
              <div className="text-sm text-green-400">Success</div>
            </div>
            <div className="w-px h-8 bg-slate-600" />
            <div className="text-center">
              <div className="text-2xl font-bold text-red-400">{failureEvents.toLocaleString()}</div>
              <div className="text-sm text-red-400">Failures</div>
            </div>
          </CardBody>
        </Card>
        
        <Card>
          <CardBody className="text-center">
            <div className="text-3xl font-bold text-slate-100">
              {Math.round((successEvents / totalEvents * 100) * 100) / 100}%
            </div>
            <div className="text-sm text-slate-400">Success Rate</div>
          </CardBody>
        </Card>
      </div>
      
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader title="Top Actions" />
          <CardBody>
            <div className="space-y-2">
              {topActions.map(([action, count]) => (
                <div key={action} className="flex items-center justify-between p-2 rounded-lg hover:bg-slate-800/50">
                  <div className="flex items-center gap-3">
                    <span className="text-slate-300">{LABELS[action] || action}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-slate-400">{count.toLocaleString()}</span>
                    <Badge tone="accent" className="text-xs">
                      {Math.round((count / totalEvents * 100) * 100) / 100}%
                    </Badge>
                  </div>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
        
        <Card>
          <CardHeader title="Most Active Admins" />
          <CardBody>
            <div className="space-y-2">
              {topActors.map(([actor, count]) => (
                <div key={actor} className="flex items-center justify-between p-2 rounded-lg hover:bg-slate-800/50">
                  <span className="text-slate-300">{actor || 'Unknown'}</span>
                  <span className="text-slate-400">{count.toLocaleString()}</span>
                </div>
              ))}
            </div>
          </CardBody>
        </Card>
      </div>
    </div>
  )
}

//Table View Component
const TableView = ({ 
  events, 
  sortBy, 
  sortOrder, 
  onSort 
}: { 
  events: AuditEventExtended[] 
  sortBy: string 
  sortOrder: 'asc' | 'desc' 
  onSort: (column: string) => void 
}) => {
  const sortedEvents = useMemo(() => {
    return [...events].sort((a, b) => {
      let aValue: string | number = ''
      let bValue: string | number = ''
      
      switch (sortBy) {
        case 'created_at':
          aValue = new Date(a.created_at).getTime()
          bValue = new Date(b.created_at).getTime()
          break
        case 'action':
          aValue = LABELS[a.action] || a.action
          bValue = LABELS[b.action] || b.action
          break
        case 'actor_username':
          aValue = a.actor_username || ''
          bValue = b.actor_username || ''
          break
        case 'outcome':
          aValue = a.outcome
          bValue = b.outcome
          break
        default:
          aValue = (a as Record<string, unknown>)[sortBy] as string || ''
          bValue = (b as Record<string, unknown>)[sortBy] as string || ''
      }
      
      if (aValue < bValue) return sortOrder === 'asc' ? -1 : 1
      if (aValue > bValue) return sortOrder === 'asc' ? 1 : -1
      return 0
    })
  }, [events, sortBy, sortOrder])
  
  const handleSort = (column: string) => {
    if (sortBy === column) {
      onSort('') // Reset sort
    } else {
      onSort(column)
    }
  }
  
  const renderSortIcon = (column: string) => {
    if (sortBy !== column) return <ChevronDown className="h-4 w-4 text-slate-500" />
    return sortOrder === 'asc' 
      ? <ChevronUp className="h-4 w-4 text-slate-300" /> 
      : <ChevronDown className="h-4 w-4 text-slate-300" />
  }
  
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="text-left text-slate-400 border-b border-slate-700">
          <tr>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('created_at')}>
              <div className="flex items-center gap-1">
                Date/Time {renderSortIcon('created_at')}
              </div>
            </th>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('action')}>
              <div className="flex items-center gap-1">
                Action {renderSortIcon('action')}
              </div>
            </th>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('actor_username')}>
              <div className="flex items-center gap-1">
                Actor {renderSortIcon('actor_username')}
              </div>
            </th>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('target_username')}>
              <div className="flex items-center gap-1">
                Target {renderSortIcon('target_username')}
              </div>
            </th>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('tenant_id')}>
              <div className="flex items-center gap-1">
                Tenant {renderSortIcon('tenant_id')}
              </div>
            </th>
            <th className="pb-3 pr-4 font-medium cursor-pointer hover:text-slate-200" onClick={() => handleSort('outcome')}>
              <div className="flex items-center gap-1">
                Outcome {renderSortIcon('outcome')}
              </div>
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedEvents.map((event) => (
            <tr key={event.id} className="border-b border-slate-800 hover:bg-slate-800/30">
              <td className="py-3 pr-4 text-slate-200 whitespace-nowrap">
                <div>
                  <div>{formatDate(event.created_at)}</div>
                  <div className="text-xs text-slate-500">{relativeTime(event.created_at)}</div>
                </div>
              </td>
              <td className="py-3 pr-4 text-slate-200">
                <div className="flex items-center gap-2">
                  <span className={`px-2 py-1 rounded text-xs ${getCategoryColorClass(event.category || '')}`}>
                    {event.category ? ACTION_CATEGORIES[event.category as keyof typeof ACTION_CATEGORIES]?.label : 'Unknown'}
                  </span>
                  {LABELS[event.action] || event.action}
                </div>
              </td>
              <td className="py-3 pr-4 text-slate-300">{event.actor_username || '—'}</td>
              <td className="py-3 pr-4 text-slate-300">{event.target_username || '—'}</td>
              <td className="py-3 pr-4 text-slate-300">{event.tenant_id || '—'}</td>
              <td className="py-3 pr-4">
                <Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>
                  {event.outcome}
                </Badge>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

//Timeline View Component
const TimelineView = ({ events }: { events: AuditEventExtended[] }) => {
  // Group events by date
  const eventsByDate = useMemo(() => {
    const grouped: Record<string, AuditEventExtended[]> = {}
    events.forEach(event => {
      const date = new Date(event.created_at).toLocaleDateString('en-US', {
        year: 'numeric',
        month: 'long',
        day: 'numeric'
      })
      if (!grouped[date]) {
        grouped[date] = []
      }
      grouped[date].push(event)
    })
    return grouped
  }, [events])

  // Format time from ISO string
  const formatTime = (dateString: string) => {
    const date = new Date(dateString)
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false
    })
  }

  return (
    <div className="relative">
      {/* Vertical timeline line */}
      <div className="absolute left-6 top-4 bottom-4 w-0.5 bg-gradient-to-b from-slate-600 to-slate-700" />
      
      <div className="space-y-8 ml-12">
        {Object.entries(eventsByDate).map(([date, dateEvents], dateIndex) => (
          <div key={date} className="relative">
            {/* Date header */}
            <div className="relative mb-6">
              <div className="absolute left-0 top-3 w-12 h-0.5 bg-slate-600" />
              <div className="ml-12">
                <div className="text-lg font-semibold text-slate-200 bg-slate-800/80 px-4 py-2 rounded-lg border border-slate-700 inline-block">
                  {date}
                </div>
                <div className="text-xs text-slate-500 mt-1 text-center">
                  {dateEvents.length} {dateEvents.length === 1 ? 'event' : 'events'}
                </div>
              </div>
            </div>

            {/* Events for this date */}
            <div className="space-y-4">
              {dateEvents.map((event, eventIndex) => {
                const categoryLabel = event.category 
                  ? ACTION_CATEGORIES[event.category as keyof typeof ACTION_CATEGORIES]?.label 
                  : 'Unknown'
                const categoryColor = getCategoryColorClass(event.category || '')
                const outcomeColor = getOutcomeColorClass(event.outcome)
                const isLatest = dateIndex === 0 && eventIndex === 0
                
                return (
                  <div key={event.id} className="relative group">
                    {/* Latest indicator for the most recent event */}
                    {isLatest && (
                      <div className="absolute -top-8 left-0 ml-4">
                        <span className="bg-accent-600 text-white text-xs font-medium px-2 py-1 rounded-full animate-pulse shadow-lg">
                          Latest
                        </span>
                      </div>
                    )}
                    {/* Timeline connector dot with category-based colors and pulse for latest */}
                    <div className={`absolute -left-12 top-6 w-4 h-4 rounded-full border-2 border-white dark:border-slate-800 shadow-lg transition-all duration-300 ${isLatest ? 'ring-2 ring-accent-500 ring-opacity-50' : ''}`} 
                         style={{
                           backgroundColor: event.outcome === 'success' ? '#22c55e' : event.outcome === 'failure' ? '#ef4444' : '#64748b'
                         }} />
                    
                    {/* Timeline vertical connector for non-first events */}
                    {eventIndex > 0 && (
                      <div className="absolute -left-10 top-10 bottom-0 w-0.5 bg-slate-600" 
                           style={{ height: 'calc(100% - 2rem)' }} />
                    )}
                    
                    {/* Event card with enhanced styling */}
                    <div className="group relative transition-all duration-200 hover:translate-x-1 hover:-translate-y-0.5">
                      <Card className="border-l-4 border-transparent hover:border-slate-600 transition-all duration-200 group-hover:shadow-lg group-hover:border-l-accent-500">
                        <CardHeader
                          title={
                            <div className="flex items-center gap-3">
                              <span className={categoryColor + ' px-3 py-1 rounded-full text-xs font-medium'}>
                                {categoryLabel}
                              </span>
                              <span className="text-slate-100 font-semibold flex-1">
                                {LABELS[event.action] || event.action}
                              </span>
                              <span className={`px-3 py-1 rounded-full text-xs font-medium ${outcomeColor}`}>
                                {event.outcome}
                              </span>
                            </div>
                          }
                          description={
                            <div className="flex items-center justify-between text-xs text-slate-400 mt-2">
                              <div className="flex items-center gap-4">
                                <span className="flex items-center gap-1.5">
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                                  </svg>
                                  {formatTime(event.created_at)}
                                </span>
                                <span className="flex items-center gap-1.5">
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
                                  </svg>
                                  {event.actor_username || 'System'}
                                </span>
                              </div>
                              {event.relative_time && (
                                <span className="text-slate-500 italic">{event.relative_time}</span>
                              )}
                            </div>
                          }
                        />
                        <CardBody className="space-y-3">
                          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                            {event.target_username && event.target_username !== event.actor_username && (
                              <div className="flex items-center gap-2">
                                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.653-.124-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.653.124-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0zm6 3a2 2 0 11-4 0 2 2 0 014 0zM7 10a2 2 0 11-4 0 2 2 0 014 0z" />
                                </svg>
                                <div>
                                  <span className="font-medium text-slate-400">Target:</span>
                                  <span className="text-slate-200 ml-1">{event.target_username}</span>
                                </div>
                              </div>
                            )}
                            {event.tenant_id && (
                              <div className="flex items-center gap-2">
                                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5M9 7h1m-1 4h1m4-4h1m-1 4h1m-5 10v-5a1 1 0 011-1h2a1 1 0 011 1v5m-4 0h4" />
                                </svg>
                                <div>
                                  <span className="font-medium text-slate-400">Tenant:</span>
                                  <span className="text-slate-200 ml-1">{event.tenant_id}</span>
                                </div>
                              </div>
                            )}
                            {event.ip_address && (
                              <div className="flex items-center gap-2">
                                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.111 16.404a5.5 5.5 0 017.778 0M12 20h.01m-7.08-7.071c3.904-3.905 10.236-3.905 14.141 0M1.394 9.393c5.857-5.857 15.355-5.857 21.213 0" />
                                </svg>
                                <div>
                                  <span className="font-medium text-slate-400">IP:</span>
                                  <span className="text-slate-200 ml-1">{event.ip_address}</span>
                                </div>
                              </div>
                            )}
                            {event.resource_type && (
                              <div className="flex items-center gap-2">
                                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
                                </svg>
                                <div>
                                  <span className="font-medium text-slate-400">Resource:</span>
                                  <span className="text-slate-200 ml-1">{event.resource_type}{event.resource_id ? `/${event.resource_id}` : ''}</span>
                                </div>
                              </div>
                            )}
                          </div>
                          {describeDetails(event.details || {}) && (
                            <div className="pt-3 border-t border-slate-700/50">
                              <span className="text-sm text-slate-400 font-medium">Details: </span>
                              <span className="text-sm text-slate-300">{describeDetails(event.details || {})}</span>
                            </div>
                          )}
                        </CardBody>
                      </Card>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

//Selections Checkbox for table view
const SelectionCheckbox = ({ 
  selectedEvents, 
  event, 
  onToggle 
}: { 
  selectedEvents: Set<number> 
  event: AuditEventExtended 
  onToggle: (eventId: number) => void 
}) => {
  const isSelected = selectedEvents.has(event.id)
  
  return (
    <input
      type="checkbox"
      checked={isSelected}
      onChange={() => onToggle(event.id)}
      className="rounded border-slate-600 bg-slate-800 text-accent-500 focus:ring-accent-500"
    />
  )
}

//Main Audit History Component
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
    preset: 'last_7_days' as FilterPreset
  })
  
  const [viewMode, setViewMode] = useState<ViewMode>('table')
  const [selectedEvents, setSelectedEvents] = useState<Set<number>>(new Set())
  const [showRefreshing, setShowRefreshing] = useState(false)
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  
  // Load saved filters
  useEffect(() => {
    const savedFilters = loadFiltersFromStorage()
    if (savedFilters) {
      setDraft(prev => ({
        ...prev,
        ...savedFilters,
        preset: savedFilters.start_date && savedFilters.end_date ? 'custom' : 'last_7_days'
      }))
    }
  }, [])
  
  // Apply filters
  const applyFilters = useCallback(() => {
    setFilters({
      ...draft,
      limit: PAGE_SIZE,
      offset: 0
    })
    saveFiltersToStorage(draft)
  }, [draft])
  
  // Debounced apply for search
  const debouncedApply = useCallback(debounce(applyFilters, 500), [applyFilters])
  
  // Handle search change
  useEffect(() => {
    if (draft.search === '') {
      applyFilters()
    } else {
      debouncedApply()
    }
  }, [draft.search, applyFilters, debouncedApply])
  
  // Main data fetch
  const state = useAsync((signal) => auditApiExtended.list(filters, signal), [filters])
  
  // Statistics fetch
  const statsState = useAsync((signal) => {
    const statsFilters = { ...filters, limit: 10000, offset: 0 }
    return auditApiExtended.getStatistics(statsFilters, signal)
  }, [filters])
  
  const page = state.data
  const statistics = statsState.data
  
  const start = page && page.total ? page.offset + 1 : 0
  const end = page ? Math.min(page.offset + page.events.length, page.total) : 0
  
  const handlePresetDateChange = (newPreset: FilterPreset, startDate?: string, endDate?: string) => {
    setDraft(prev => ({
      ...prev,
      preset: newPreset,
      start_date: startDate || '',
      end_date: endDate || ''
    }))
  }
  
  const handlePresetApply = (presetFilters: Record<string, unknown>) => {
    const newFilters = { ...draft, ...presetFilters }
    setDraft(newFilters)
    setFilters({
      ...newFilters,
      limit: PAGE_SIZE,
      offset: 0
    })
    saveFiltersToStorage(newFilters)
  }
  
  const handleExportSuccess = () => {
    setToastMessage('Export completed successfully!')
    setTimeout(() => setToastMessage(null), 3000)
  }
  
  const toggleEventSelection = (eventId: number) => {
    setSelectedEvents(prev => {
      const newSet = new Set(prev)
      if (newSet.has(eventId)) {
        newSet.delete(eventId)
      } else {
        newSet.add(eventId)
      }
      return newSet
    })
  }
  
  const selectAllEvents = () => {
    if (page?.events) {
      const allIds = new Set<number>(page.events.map(event => event.id))
      setSelectedEvents(allIds)
    }
  }
  
  const clearSelection = () => {
    setSelectedEvents(new Set())
  }
  
  const handleSort = (column: string) => {
    setFilters(prev => {
      const newSortBy = prev.sort_by === column ? '' : column
      return {
        ...prev,
        sort_by: newSortBy,
        sort_order: newSortBy === '' ? 'desc' : (prev.sort_by === column && prev.sort_order === 'asc' ? 'desc' : 'asc')
      }
    })
  }
  
  const refreshData = () => {
    setShowRefreshing(true)
    state.retry()
    statsState.retry()
    setTimeout(() => setShowRefreshing(false), 1000)
  }
  
  const formattedEvents = useMemo(() => {
    return page?.events.map(formatEventForDisplay) || []
  }, [page?.events])
  
  return (
    <div>
      <PageHeader
        title="Audit history"
        description="Review admin and sub-admin logins and account or tenant setup changes. Records are retained for one year."
        meta={<Badge tone="accent">Superadmin only</Badge>}
      />
      
      {toastMessage && (
        <div className="mb-4">
          <Toast tone="success" onDismiss={() => setToastMessage(null)}>
            {toastMessage}
          </Toast>
        </div>
      )}

      {/* Quick Actions Bar */}
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4 flex-wrap">
            <ViewToggle viewMode={viewMode} onViewChange={setViewMode} />
            <FilterPresets onApplyPreset={handlePresetApply} />
            <ExportMenu events={formattedEvents} filters={filters} onExportSuccess={handleExportSuccess} />
            <Button 
              variant="secondary" 
              icon={showRefreshing ? <RefreshCw className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
              onClick={refreshData}
              disabled={state.loading}
            >
              Refresh
            </Button>
          </div>
          
          <div className="flex items-center gap-4">
            {selectedEvents.size > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-sm text-slate-300">{selectedEvents.size} selected</span>
                <Button variant="secondary" size="sm" onClick={clearSelection}>
                  Clear
                </Button>
                <ExportMenu 
                  events={formattedEvents.filter(event => selectedEvents.has(event.id))} 
                  filters={filters} 
                  onExportSuccess={handleExportSuccess} 
                />
              </div>
            )}
          </div>
        </CardBody>
      </Card>

      {/* Statistics Dashboard */}
      {viewMode === 'table' && (
        <StatisticsDashboard statistics={statistics} loading={statsState.loading} />
      )}

      {/* Filters Card */}
      <Card className="mb-4">
        <CardBody className="space-y-4">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold text-slate-200">Filters</h3>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" onClick={applyFilters}>
                Apply
              </Button>
              <Button 
                variant="ghost" 
                size="sm" 
                onClick={() => {
                  setDraft({
                    search: '', 
                    actor: '', 
                    action: '', 
                    category: '', 
                    tenant_id: '', 
                    outcome: '',
                    start_date: '', 
                    end_date: '',
                    preset: 'last_7_days'
                  })
                }}
              >
                Clear All
              </Button>
            </div>
          </div>
          
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Input 
              label="Search" 
              placeholder="Actor, target, action, or resource" 
              value={draft.search} 
              onChange={(event) => setDraft((value) => ({ ...value, search: event.target.value }))}
            />
            <Input 
              label="Actor username" 
              value={draft.actor} 
              onChange={(event) => setDraft((value) => ({ ...value, actor: event.target.value }))}
            />
            <Select 
              label="Action" 
              value={draft.action} 
              onChange={(event) => setDraft((value) => ({ ...value, action: event.target.value }))}
            >
              <option value="">All actions</option>
              {Object.entries(LABELS).map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </Select>
            <Select 
              label="Category" 
              value={draft.category} 
              onChange={(event) => setDraft((value) => ({ ...value, category: event.target.value }))}
            >
              <option value="">All categories</option>
              {Object.entries(ACTION_CATEGORIES).map(([value, config]) => (
                <option key={value} value={value}>{config.label}</option>
              ))}
            </Select>
            <Input 
              label="Tenant ID" 
              value={draft.tenant_id} 
              onChange={(event) => setDraft((value) => ({ ...value, tenant_id: event.target.value }))}
            />
            <Select 
              label="Outcome" 
              value={draft.outcome} 
              onChange={(event) => setDraft((value) => ({ ...value, outcome: event.target.value as AuditOutcome | '' }))}
            >
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="failure">Failure</option>
            </Select>
            <DateRangePicker 
              startDate={draft.start_date} 
              endDate={draft.end_date} 
              preset={draft.preset} 
              onChange={handlePresetDateChange} 
            />
          </div>
        </CardBody>
      </Card>

      {state.error && <Alert tone="danger" title="Could not load audit history">{state.error}</Alert>}
      {state.loading && <LoadingBlock label="Loading audit history..." />}
      
      {page?.events.length === 0 && !state.loading && (
        <Card>
          <EmptyState title="No activity found" description="Try changing the filters or date range." />
        </Card>
      )}
      
      {page && page.events.length > 0 && (
        <>
          {/* Results summary */}
          <div className="mb-3 flex items-center justify-between text-xs text-slate-500">
            <span>Showing {start}–{end} of {page.total.toLocaleString()} events</span>
            <div className="flex items-center gap-4">
              <span>Sort: {filters.sort_by ? LABELS[filters.sort_by] || filters.sort_by : 'Date'} ({filters.sort_order})</span>
            </div>
          </div>

          {/* View switching */}
          {viewMode === 'table' && (
            <div className="mb-4">
              <TableView 
                events={formattedEvents} 
                sortBy={filters.sort_by || ''} 
                sortOrder={filters.sort_order || 'desc'} 
                onSort={handleSort}
              />
            </div>
          )}
          
          {viewMode === 'cards' && (
            <div className="space-y-3">
              {formattedEvents.map((event) => (
                <Card key={event.id}>
                  <CardHeader
                    title={LABELS[event.action] ?? event.action.replace(/_/g, ' ')}
                    description={`${event.actor_username || event.target_username || 'Unknown account'}${event.actor_role ? ` · ${event.actor_role.replace(/_/g, ' ')}` : ''} · ${formatDate(event.created_at)}`}
                    actions={
                      <div className="flex gap-2">
                        <Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>
                        <span className={`px-2 py-1 rounded text-xs ${getCategoryColorClass(event.category || '')}`}>
                          {event.category ? ACTION_CATEGORIES[event.category as keyof typeof ACTION_CATEGORIES]?.label : 'Unknown'}
                        </span>
                      </div>
                    }
                  />
                  <CardBody className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-400">
                    {event.target_username && event.target_username !== event.actor_username && <span>Account: {event.target_username}</span>}
                    {event.tenant_id && <span>Tenant: {event.tenant_id}</span>}
                    {event.ip_address && <span>IP: {event.ip_address}</span>}
                    {event.resource_type && <span>{event.resource_type.replace(/_/g, ' ')}{event.resource_id ? ` · ${event.resource_id}` : ''}</span>}
                    {describeDetails(event.details) && <span>{describeDetails(event.details)}</span>}
                    {event.action === 'login' && event.outcome === 'failure' && <span>Invalid credentials</span>}
                  </CardBody>
                </Card>
              ))}
            </div>
          )}
          
          {viewMode === 'timeline' && (
            <TimelineView events={formattedEvents} />
          )}

          {/* Pagination */}
          <div className="mt-4 flex items-center justify-between">
            <Button 
              variant="secondary" 
              disabled={page.offset === 0 || state.loading} 
              icon={<ChevronLeft className="h-4 w-4" />} 
              onClick={() => setFilters((value) => ({ ...value, offset: Math.max(0, (value.offset ?? 0) - PAGE_SIZE) }))}
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
              onClick={() => setFilters((value) => ({ ...value, offset: (value.offset ?? 0) + PAGE_SIZE }))}
            >
              Next
            </Button>
          </div>
        </>
      )}
    </div>
  )
}

// Re-export types for external use
export type { ViewMode, FilterPreset } from './audit-history.types'
