/**
 * Audit Log Page Component - Healthy Earth Theme
 * Premium Audit Log & Event Timeline for SaaS Admin Panel
 */
import React, { useState, useMemo, useEffect } from 'react';
import { useAsync } from '@/lib/hooks'
import { formatDate, relativeTime } from '@/lib/format'
import {
  Calendar, 
  ChevronDown, 
  ChevronLeft, 
  ChevronRight,
  Clock,
  Download,
  Filter,
  Grid3X3,
  LayoutTemplate,
  List,
  LogIn,
  Mail,
  MessageSquare,
  RefreshCw,
  Send,
  Settings,
  Table2,
  Terminal,
  TrendingUp,
  User,
  X
} from 'lucide-react';
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock, Toast } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

// API service
const fetchAuditLogs = async (params: Record<string, unknown>) => {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      query.set(key, String(value));
    }
  });
  
  const response = await fetch(`/api/audit-logs?${query.toString()}`);
  if (!response.ok) {
    throw new Error('Failed to fetch audit logs');
  }
  return response.json();
};

// Action to icon mapping
const actionIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  login: LogIn,
  logout: LogIn,
  message_sent: Send,
  message_received: Mail,
  campaign_started: TrendingUp,
  campaign_stopped: X,
  handover_toggled: Settings,
  settings_updated: Settings,
  system_event: Terminal,
  user_created: User,
  user_updated: User,
  user_deleted: X,
  chat_session_started: MessageSquare,
  chat_session_ended: X,
};

// Category to icon mapping
const categoryIcons: Record<string, React.ComponentType<{ className?: string }>> = {
  Authentication: User,
  Messaging: MessageSquare,
  Campaigns: TrendingUp,
  System: Settings,
  Users: User,
};

// Status color classes for Healthy Earth theme
const statusColors: Record<string, string> = {
  success: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-amber-100 text-amber-700',
  unknown: 'bg-stone-100 text-stone-700',
};

// Action labels
const actionLabels: Record<string, string> = {
  login: 'Logged in',
  logout: 'Logged out', 
  message_sent: 'Message sent',
  message_received: 'Message received',
  campaign_started: 'Campaign started',
  campaign_stopped: 'Campaign stopped',
  handover_toggled: 'Handover toggled',
  settings_updated: 'Settings updated',
  system_event: 'System event',
  user_created: 'User created',
  user_updated: 'User updated',
  user_deleted: 'User deleted',
  chat_session_started: 'Chat started',
  chat_session_ended: 'Chat ended',
};

// Preset filter options
interface FilterPreset {
  name: string
  filters: Record<string, unknown>
}

const presetFilters: FilterPreset[] = [
  { name: 'Recent Logins', filters: { action: 'login', days: 1 } },
  { name: 'Failed Events', filters: { status: 'failed', days: 7 } },
  { name: 'System Events', filters: { category: 'System', days: 7 } },
  { name: 'User Activity', filters: { category: 'Users', days: 7 } },
  { name: 'Campaign Activity', filters: { category: 'Campaigns', days: 30 } },
  { name: 'Today', filters: { days: 1 } },
  { name: 'This Week', filters: { days: 7 } },
];

// Date presets
interface DatePreset {
  value: number
  label: string
}

const datePresets: DatePreset[] = [
  { value: 1, label: 'Last 24 hours' },
  { value: 7, label: 'Last 7 days' },
  { value: 30, label: 'Last 30 days' },
];

// Filter options
const actionOptions = [
  { value: '', label: 'All Actions' },
  { value: 'login', label: 'Login' },
  { value: 'logout', label: 'Logout' },
  { value: 'message_sent', label: 'Message Sent' },
  { value: 'message_received', label: 'Message Received' },
  { value: 'campaign_started', label: 'Campaign Started' },
  { value: 'campaign_stopped', label: 'Campaign Stopped' },
  { value: 'handover_toggled', label: 'Handover Toggled' },
  { value: 'settings_updated', label: 'Settings Updated' },
];

const categoryOptions = [
  { value: '', label: 'All Categories' },
  { value: 'Authentication', label: 'Authentication' },
  { value: 'Messaging', label: 'Messaging' },
  { value: 'Campaigns', label: 'Campaigns' },
  { value: 'System', label: 'System' },
  { value: 'Users', label: 'Users' },
];

const statusOptions = [
  { value: '', label: 'All Statuses' },
  { value: 'success', label: 'Success' },
  { value: 'failed', label: 'Failed' },
  { value: 'pending', label: 'Pending' },
];

// Pagination and sorting types
type ViewType = 'timeline' | 'table' | 'cards'

interface AuditLogEvent {
  id: number | string
  timestamp: string
  actor: string
  action: string
  category: string
  status: string
  description: string
  metadata?: Record<string, unknown>
}

interface AuditLogFilters {
  search: string
  actor: string
  action: string
  category: string
  days: number
}

// Sub-components
const ViewToggle = ({ view, onChange }: { view: ViewType; onChange: (view: ViewType) => void }) => {
  const views = [
    { id: 'timeline' as ViewType, label: 'Timeline', icon: List },
    { id: 'table' as ViewType, label: 'Table', icon: Table2 },
    { id: 'cards' as ViewType, label: 'Cards', icon: Grid3X3 },
  ];
  
  return (
    <div className="inline-flex bg-white rounded-lg border border-stone-200 p-1">
      {views.map((v) => {
        const Icon = v.icon;
        return (
          <button
            key={v.id}
            onClick={() => onChange(v.id)}
            className={`flex items-center gap-2 px-4 py-2 text-sm font-medium rounded-md transition-all ${
              view === v.id
                ? 'bg-amber-50 text-amber-600'
                : 'text-stone-600 hover:bg-stone-50 hover:text-stone-900'
            }`}
          >
            <Icon className="w-4 h-4" />
            {v.label}
          </button>
        );
      })}
    </div>
  );
};

const PresetDropdown = ({ onSelect }: { onSelect: (filters: Record<string, unknown>) => void }) => {
  const [isOpen, setIsOpen] = useState(false);
  
  return (
    <div className="relative">
      <Button 
        variant="secondary" 
        size="sm" 
        onClick={() => setIsOpen(!isOpen)}
      >
        <Filter className="w-4 h-4" />
        Presets
        <ChevronDown className="w-4 h-4 ml-1" />
      </Button>
      
      {isOpen && (
        <div className="absolute z-10 w-48 mt-2 bg-white rounded-lg border border-stone-200 shadow-lg">
          <div className="py-1">
            {presetFilters.map((preset) => (
              <button
                key={preset.name}
                onClick={() => {
                  onSelect(preset.filters);
                  setIsOpen(false);
                }}
                className="block w-full px-4 py-2 text-left text-sm text-stone-700 hover:bg-stone-50"
              >
                {preset.name}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

const ExportDropdown = ({ onExport, isLoading }: { onExport: (format: string) => void; isLoading: boolean }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState('csv');
  
  return (
    <div className="relative">
      <Button 
        variant="secondary" 
        size="sm" 
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading}
      >
        <Download className="w-4 h-4" />
        Export
        <ChevronDown className="w-4 h-4 ml-1" />
      </Button>
      
      {isOpen && (
        <div className="absolute z-10 w-48 mt-2 bg-white rounded-lg border border-stone-200 shadow-lg p-4">
          <h3 className="font-semibold text-stone-900 mb-3">Export Format</h3>
          <div className="space-y-2">
            {['csv', 'json'].map((fmt) => (
              <label key={fmt} className="flex items-center gap-2">
                <input
                  type="radio"
                  name="exportFormat"
                  value={fmt}
                  checked={selectedFormat === fmt}
                  onChange={() => setSelectedFormat(fmt)}
                  className="text-amber-600 focus:ring-amber-500"
                />
                <span className="text-sm text-stone-700 capitalize">{fmt}</span>
              </label>
            ))}
          </div>
          <Button
            variant="primary"
            className="w-full mt-4"
            size="sm"
            onClick={() => {
              onExport(selectedFormat);
              setIsOpen(false);
            }}
          >
            Export
          </Button>
        </div>
      )}
    </div>
  );
};

const DateRangeSelect = ({ value, onChange }: { value: number; onChange: (value: number) => void }) => {
  return (
    <div className="flex items-center gap-2">
      <Calendar className="w-5 h-5 text-stone-500" />
      <Select 
        value={String(value)} 
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="w-full"
      >
        {datePresets.map((preset) => (
          <option key={preset.value} value={preset.value}>
            {preset.label}
          </option>
        ))}
      </Select>
    </div>
  );
};

const StatusBadge = ({ status }: { status: string }) => {
  const colorClass = statusColors[status] || statusColors.unknown;
  return (
    <Badge className={colorClass}>
      {status}
    </Badge>
  );
};

const CategoryBadge = ({ category }: { category: string }) => {
  return (
    <Badge tone="secondary" className="text-xs">
      {category}
    </Badge>
  );
};

// Main View Components
const TimelineView = ({ events, isLoading }: { events?: AuditLogEvent[]; isLoading: boolean }) => {
  if (isLoading) {
    return (
      <div className="space-y-4">
        {[...Array(5)].map((_, i) => (
          <div key={i} className="animate-pulse">
            <div className="flex gap-4">
              <div className="w-2 h-2 bg-stone-300 rounded-full mt-2"></div>
              <div className="flex-1 bg-white p-4 rounded-lg border border-stone-200">
                <div className="h-4 bg-stone-200 rounded w-3/4 mb-2"></div>
                <div className="h-3 bg-stone-100 rounded w-1/2"></div>
              </div>
            </div>
          </div>
        ))}
      </div>
    );
  }
  
  if (!events || events.length === 0) {
    return (
      <Card>
        <EmptyState 
          title="No events found" 
          description="Try adjusting your filters or date range"
          icon={<List className="w-8 h-8" />}
        />
      </Card>
    );
  }
  
  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-stone-300" />
      
      <div className="space-y-6 ml-8">
        {events.map((event) => {
          const Icon = actionIcons[event.action] || MessageSquare;
          const label = actionLabels[event.action] || event.action;
          const CategoryIcon = categoryIcons[event.category] || Settings;
          
          return (
            <div key={event.id} className="relative">
              {/* Timeline dot */}
              <div className="absolute -left-8 top-2 w-4 h-4 bg-white border-2 border-stone-300 rounded-full" />
              
              {/* Event card */}
              <Card>
                <CardBody className="p-0">
                  <div className="p-6">
                    <div className="flex items-start gap-4">
                      {/* Action icon */}
                      <div className="p-3 bg-stone-50 rounded-lg">
                        <Icon className="w-6 h-6 text-amber-600" />
                      </div>
                      
                      <div className="flex-1">
                        {/* Timestamp and relative time */}
                        <div className="flex items-center gap-4 text-sm text-stone-500 mb-2">
                          <span>{formatDate(event.timestamp)}</span>
                          <span className="text-stone-400">{relativeTime(event.timestamp)}</span>
                        </div>
                        
                        {/* Event details */}
                        <div className="mb-3">
                          <h3 className="text-lg font-semibold text-stone-900">
                            {label}
                          </h3>
                          <p className="text-stone-600">
                            by <span className="font-medium">{event.actor}</span>
                          </p>
                        </div>
                        
                        {/* Description */}
                        {event.description && (
                          <p className="text-stone-600 text-sm mb-3">{event.description}</p>
                        )}
                        
                        {/* Badges */}
                        <div className="flex items-center gap-3">
                          <StatusBadge status={event.status} />
                          <CategoryBadge category={event.category} />
                        </div>
                      </div>
                    </div>
                  </div>
                </CardBody>
              </Card>
            </div>
          );
        })}
      </div>
    </div>
  );
};

const TableView = ({ 
  events, 
  isLoading, 
  sortBy, 
  sortOrder, 
  onSort 
}: { 
  events?: AuditLogEvent[]; 
  isLoading: boolean;
  sortBy: string;
  sortOrder: 'asc' | 'desc';
  onSort: (column: string) => void
}) => {
  if (isLoading) {
    return (
      <LoadingBlock label="Loading audit logs..." />
    );
  }
  
  if (!events || events.length === 0) {
    return (
      <Card>
        <EmptyState 
          title="No events found" 
          description="Try adjusting your filters"
          icon={<Table2 className="w-8 h-8" />}
        />
      </Card>
    );
  }
  
  const sortedEvents = [...events].sort((a, b) => {
    let aVal: string | Date = a[sortBy as keyof AuditLogEvent] as string || '';
    let bVal: string | Date = b[sortBy as keyof AuditLogEvent] as string || '';
    
    if (sortBy === 'timestamp') {
      aVal = new Date(a.timestamp);
      bVal = new Date(b.timestamp);
    }
    
    if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
    if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
    return 0;
  });
  
  const getSortIcon = (column: string) => {
    if (sortBy !== column) return <ChevronDown className="w-4 h-4 text-stone-400" />;
    return sortOrder === 'asc' 
      ? <ChevronUp className="w-4 h-4 text-stone-600" /> 
      : <ChevronDown className="w-4 h-4 text-stone-600" />;
  };
  
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead className="bg-white">
          <tr className="border-b border-stone-200">
            <th 
              onClick={() => onSort('action')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Event {getSortIcon('action')}
            </th>
            <th 
              onClick={() => onSort('actor')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Actor {getSortIcon('actor')}
            </th>
            <th 
              onClick={() => onSort('category')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Category {getSortIcon('category')}
            </th>
            <th 
              onClick={() => onSort('status')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Status {getSortIcon('status')}
            </th>
            <th 
              onClick={() => onSort('timestamp')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Timestamp {getSortIcon('timestamp')}
            </th>
          </tr>
        </thead>
        <tbody>
          {sortedEvents.map((event) => {
            const Icon = actionIcons[event.action];
            const label = actionLabels[event.action] || event.action;
            return (
              <tr 
                key={event.id} 
                className="border-b border-stone-100 hover:bg-stone-50 transition-colors"
              >
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    {Icon && (
                      <div className="p-1 bg-stone-50 rounded">
                        <Icon className="w-4 h-4 text-amber-600" />
                      </div>
                    )}
                    <span className="font-medium text-stone-900">{label}</span>
                  </div>
                </td>
                <td className="px-6 py-4 text-stone-600">{event.actor}</td>
                <td className="px-6 py-4"><CategoryBadge category={event.category} /></td>
                <td className="px-6 py-4"><StatusBadge status={event.status} /></td>
                <td className="px-6 py-4 text-stone-500 text-sm whitespace-nowrap">
                  {formatDate(event.timestamp)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const CardsView = ({ events, isLoading }: { events?: AuditLogEvent[]; isLoading: boolean }) => {
  if (isLoading) {
    return (
      <LoadingBlock label="Loading audit logs..." />
    );
  }
  
  if (!events || events.length === 0) {
    return (
      <Card>
        <EmptyState 
          title="No events found" 
          description="Try adjusting your filters"
          icon={<Grid3X3 className="w-8 h-8" />}
        />
      </Card>
    );
  }
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {events.map((event) => {
        const Icon = actionIcons[event.action] || MessageSquare;
        const label = actionLabels[event.action] || event.action;
        
        return (
          <Card key={event.id}>
            <CardBody>
              <div className="flex items-center justify-between mb-3">
                <div className="p-2 bg-stone-50 rounded-lg">
                  <Icon className="w-5 h-5 text-amber-600" />
                </div>
                <StatusBadge status={event.status} />
              </div>
              
              <h3 className="font-semibold text-stone-900 mb-2">{label}</h3>
              <p className="text-sm text-stone-500 mb-3">
                by {event.actor}
              </p>
              
              {event.description && (
                <p className="text-sm text-stone-600 mb-4 line-clamp-2">{event.description}</p>
              )}
              
              <div className="flex items-center justify-between pt-3 border-t border-stone-100">
                <CategoryBadge category={event.category} />
                <span className="text-xs text-stone-400">{relativeTime(event.timestamp)}</span>
              </div>
            </CardBody>
          </Card>
        );
      })}
    </div>
  );
};

// Pagination Component
const Pagination = ({ 
  currentPage, 
  totalPages, 
  onPageChange, 
  isLoading 
}: { 
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  isLoading: boolean
}) => {
  if (totalPages <= 1) return null;
  
  return (
    <div className="flex items-center justify-end mt-6 gap-2">
      <Button
        variant="secondary"
        disabled={currentPage === 1 || isLoading}
        icon={<ChevronLeft className="w-5 h-5" />}
        onClick={() => onPageChange(currentPage - 1)}
      >
        Previous
      </Button>
      <span className="text-sm text-stone-500 px-4">
        Page {currentPage} of {totalPages}
      </span>
      <Button
        variant="secondary"
        disabled={currentPage === totalPages || isLoading}
        icon={<ChevronRight className="w-5 h-5" />}
        onClick={() => onPageChange(currentPage + 1)}
      >
        Next
      </Button>
    </div>
  );
};

// Main Audit Log Page Component
const AuditLogPage = () => {
  // State
  const [view, setView] = useState<ViewType>('timeline');
  const [filters, setFilters] = useState<AuditLogFilters>({
    search: '',
    actor: '',
    action: '',
    category: '',
    days: 7,
  });
  const [sortBy] = useState<string>('timestamp');
  const [sortOrder] = useState<'asc' | 'desc'>('desc');
  const [page, setPage] = useState<number>(1);
  const [refreshing, setRefreshing] = useState(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  
  const limit = 20;
  
  // React Query to fetch data - using custom hook instead
  const state = useAsync<{ 
    events: AuditLogEvent[], 
    total: number,
    date_range?: { start_date: string; end_date: string; days: number }
  }>(() => {
    const params = {
      ...filters,
      limit,
      offset: (page - 1) * limit,
      sort_by: sortBy,
      sort_order: sortOrder
    };
    return fetchAuditLogs(params);
  }, [filters, page, sortBy, sortOrder]);
  
  const data = state.data;
  const isLoading = state.loading;
  const isError = state.error;
  
  // Handle filter changes
  const handleFilterChange = (name: string, value: string | number) => {
    setFilters(prev => ({ ...prev, [name]: value }));
    setPage(1); // Reset to first page when filters change
  };
  
  // Handle preset selection
  const handlePresetSelect = (presetFilters: Record<string, unknown>) => {
    setFilters(prev => ({ ...prev, ...presetFilters }));
    setPage(1);
  };
  
  // Handle refresh
  const handleRefresh = () => {
    setRefreshing(true);
    state.retry().then(() => {
      setRefreshing(false);
      setToastMessage('Audit logs refreshed successfully');
    }).catch(() => {
      setRefreshing(false);
      setToastMessage('Failed to refresh audit logs');
    });
  };
  
  // Handle export
  const handleExport = (format: string) => {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== '' && value !== undefined) {
        params.set(key, String(value));
      }
    });
    params.set('format', format);
    
    window.open(`/api/audit-logs/export?${params.toString()}`, '_blank');
    setToastMessage(`Exporting as ${format.toUpperCase()}...`);
  };
  
  // Calculate total pages
  const totalPages = data ? Math.ceil(data.total / limit) : 0;
  
  return (
    <div className="min-h-screen bg-stone-50">
      {/* Header */}
      <PageHeader
        title="Audit Log"
        description="Track system activity and events"
      />
      
      {/* Toast Message */}
      {toastMessage && (
        <div className="mb-4">
          <Toast tone="success" onDismiss={() => setToastMessage(null)}>
            {toastMessage}
          </Toast>
        </div>
      )}
      
      {/* Top Toolbar */}
      <Card className="mb-4">
        <CardBody className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <ViewToggle view={view} onChange={setView} />
          </div>
          
          <div className="flex items-center gap-3">
            <PresetDropdown onSelect={handlePresetSelect} />
            <ExportDropdown onExport={handleExport} isLoading={isLoading} />
            <Button 
              variant="secondary" 
              onClick={handleRefresh}
              disabled={isLoading || refreshing}
              icon={refreshing ? <RefreshCw className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
            >
              Refresh
            </Button>
          </div>
        </CardBody>
      </Card>
      
      {/* Filter Bar */}
      <Card className="mb-6">
        <CardBody>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-4">
            <Input
              placeholder="Search events..."
              value={filters.search}
              onChange={(e) => handleFilterChange('search', e.target.value)}
            />
            
            <Select 
              value={filters.actor} 
              onChange={(e) => handleFilterChange('actor', e.target.value)}
            >
              <option value="">All Actors</option>
              <option value="admin1">admin1</option>
              <option value="System">System</option>
              <option value="Bot">Bot</option>
            </Select>
            
            <Select 
              value={filters.action} 
              onChange={(e) => handleFilterChange('action', e.target.value)}
            >
              <option value="">All Actions</option>
              {actionOptions.slice(1).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </Select>
            
            <Select 
              value={filters.category} 
              onChange={(e) => handleFilterChange('category', e.target.value)}
            >
              <option value="">All Categories</option>
              {categoryOptions.slice(1).map((option) => (
                <option key={option.value} value={option.value}>{option.label}</option>
              ))}
            </Select>
            
            <DateRangeSelect
              value={filters.days}
              onChange={(value) => handleFilterChange('days', value)}
            />
          </div>
          
          <Button 
            variant="ghost" 
            size="sm" 
            onClick={() => setFilters({
              search: '',
              actor: '',
              action: '',
              category: '',
              days: 7,
            })}
          >
            <X className="w-4 h-4" />
            Clear Filters
          </Button>
        </CardBody>
      </Card>
      
      {/* Results Summary */}
      {data && (
        <div className="mb-4 text-sm text-stone-600">
          Showing {data.offset + 1}-{Math.min(data.offset + data.events.length, data.total)} of {data.total} events
          {data.date_range && (
            <span className="ml-4">
              ({formatDate(data.date_range.start_date)} to {formatDate(data.date_range.end_date)})
            </span>
          )}
        </div>
      )}
      
      {/* Error State */}
      {isError && (
        <Alert tone="danger" title="Failed to load audit logs">
          {isError}
        </Alert>
      )}
      
      {/* Views */}
      {view === 'timeline' && (
        <TimelineView events={data?.events} isLoading={isLoading} />
      )}
      
      {view === 'table' && (
        <TableView 
          events={data?.events} 
          isLoading={isLoading} 
          sortBy={sortBy} 
          sortOrder={sortOrder}
          onSort={(column) => { /* Sort logic here */ }}
        />
      )}
      
      {view === 'cards' && (
        <CardsView events={data?.events} isLoading={isLoading} />
      )}
      
      {/* Pagination */}
      {data && (
        <Pagination
          currentPage={page}
          totalPages={totalPages}
          onPageChange={setPage}
          isLoading={isLoading}
        />
      )}
    </div>
  );
};

export default AuditLogPage;