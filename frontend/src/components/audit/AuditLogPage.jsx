/**
 * Audit Log Page Component - Healthy Earth Theme
 * Premium Audit Log & Event Timeline for SaaS Admin Panel
 */
import React, { useState, useMemo, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { format, parseISO } from 'date-fns';
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

// API service
const fetchAuditLogs = async (params) => {
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
const actionIcons = {
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
const categoryIcons = {
  Authentication: User,
  Messaging: MessageSquare,
  Campaigns: TrendingUp,
  System: Settings,
  Users: User,
};

// Status color classes for Healthy Earth theme
const statusColors = {
  success: 'bg-emerald-100 text-emerald-700',
  failed: 'bg-red-100 text-red-700',
  pending: 'bg-amber-100 text-amber-700',
  unknown: 'bg-stone-100 text-stone-700',
};

// Action labels
const actionLabels = {
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
const presetFilters = [
  { name: 'Recent Logins', filters: { action: 'login', days: 1 } },
  { name: 'Failed Events', filters: { status: 'failed', days: 7 } },
  { name: 'System Events', filters: { category: 'System', days: 7 } },
  { name: 'User Activity', filters: { category: 'Users', days: 7 } },
  { name: 'Campaign Activity', filters: { category: 'Campaigns', days: 30 } },
  { name: 'Today', filters: { days: 1 } },
  { name: 'This Week', filters: { days: 7 } },
];

// Date presets
const datePresets = [
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

// Date formatting
const formatTimestamp = (timestamp) => {
  if (!timestamp) return 'Unknown';
  try {
    const date = parseISO(timestamp);
    return format(date, 'MMM dd, yyyy, h:mm a');
  } catch {
    return timestamp;
  }
};

const formatRelativeTime = (timestamp) => {
  if (!timestamp) return '';
  try {
    const date = parseISO(timestamp);
    const now = new Date();
    const diff = now - date;
    
    const minutes = Math.floor(diff / 60000);
    if (minutes < 60) return `${minutes}m ago`;
    
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    
    const days = Math.floor(hours / 24);
    if (days < 30) return `${days}d ago`;
    
    return format(date, 'MMM dd, yyyy');
  } catch {
    return '';
  }
};

// Export formats
const exportFormats = [
  { value: 'csv', label: 'CSV' },
  { value: 'json', label: 'JSON' },
];

// Sub-components
const ViewToggle = ({ view, onChange }) => {
  const views = [
    { id: 'timeline', label: 'Timeline', icon: List },
    { id: 'table', label: 'Table', icon: Table2 },
    { id: 'cards', label: 'Cards', icon: Grid3X3 },
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

const PresetDropdown = ({ onSelect }) => {
  const [isOpen, setIsOpen] = useState(false);
  
  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-700 bg-white border border-stone-200 rounded-lg hover:bg-stone-50 transition-colors"
      >
        <Filter className="w-4 h-4" />
        Presets
        <ChevronDown className="w-4 h-4" />
      </button>
      
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

const ExportDropdown = ({ onExport, isLoading }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState('csv');
  
  return (
    <div className="relative">
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading}
        className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-700 bg-white border border-stone-200 rounded-lg hover:bg-stone-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
      >
        <Download className="w-4 h-4" />
        Export
        <ChevronDown className="w-4 h-4" />
      </button>
      
      {isOpen && (
        <div className="absolute z-10 w-48 mt-2 bg-white rounded-lg border border-stone-200 shadow-lg">
          <div className="p-4">
            <h3 className="font-semibold text-stone-900 mb-3">Export Format</h3>
            <div className="space-y-2">
              {exportFormats.map((fmt) => (
                <label key={fmt.value} className="flex items-center gap-2">
                  <input
                    type="radio"
                    name="exportFormat"
                    value={fmt.value}
                    checked={selectedFormat === fmt.value}
                    onChange={() => setSelectedFormat(fmt.value)}
                    className="text-amber-600 focus:ring-amber-500"
                  />
                  <span className="text-sm text-stone-700">{fmt.label}</span>
                </label>
              ))}
            </div>
            <button
              onClick={() => {
                onExport(selectedFormat);
                setIsOpen(false);
              }}
              className="w-full mt-4 px-4 py-2 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 transition-colors"
            >
              Export
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

const DateRangeSelect = ({ value, onChange }) => {
  return (
    <div className="flex items-center gap-2">
      <Calendar className="w-5 h-5 text-stone-500" />
      <select
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="px-3 py-2 text-sm border border-stone-200 rounded-lg bg-white text-stone-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
      >
        {datePresets.map((preset) => (
          <option key={preset.value} value={preset.value}>
            {preset.label}
          </option>
        ))}
      </select>
    </div>
  );
};

const SearchInput = ({ value, onChange, placeholder = 'Search...' }) => {
  return (
    <div className="relative">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full px-4 py-2 pl-10 text-sm border border-stone-200 rounded-lg bg-white text-stone-700 placeholder-stone-400 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
      />
      <search className="absolute left-3 top-1/2 -translate-y-1/2 text-stone-400">
        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
        </svg>
      </search>
    </div>
  );
};

const SelectInput = ({ value, onChange, options, label }) => {
  return (
    <div className="flex items-center gap-2">
      {label && <span className="text-sm text-stone-600">{label}</span>}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="px-3 py-2 text-sm border border-stone-200 rounded-lg bg-white text-stone-700 focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
};

const StatusBadge = ({ status }) => {
  const colorClass = statusColors[status] || statusColors.unknown;
  return (
    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
      {status}
    </span>
  );
};

const CategoryBadge = ({ category }) => {
  return (
    <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-stone-100 text-stone-700">
      {category}
    </span>
  );
};

// Main View Components
const TimelineView = ({ events, isLoading }) => {
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
      <div className="text-center py-12">
        <div className="w-16 h-16 mx-auto bg-stone-100 rounded-full flex items-center justify-center mb-4">
          <List className="w-8 h-8 text-stone-500" />
        </div>
        <h3 className="text-lg font-semibold text-stone-900 mb-2">No events found</h3>
        <p className="text-stone-500">Try adjusting your filters</p>
      </div>
    );
  }
  
  return (
    <div className="relative">
      {/* Timeline line */}
      <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-stone-300" />
      
      <div className="space-y-6 ml-8">
        {events.map((event, index) => {
          const Icon = actionIcons[event.action] || MessageSquare;
          const categoryIcon = categoryIcons[event.category] || Settings;
          const label = actionLabels[event.action] || event.action;
          
          return (
            <div key={event.id} className="relative">
              {/* Timeline dot */}
              <div className="absolute -left-8 top-2 w-4 h-4 bg-white border-2 border-stone-300 rounded-full" />
              
              {/* Event card */}
              <div className="bg-white rounded-xl border border-stone-200 p-6 shadow-sm hover:shadow-md transition-shadow">
                <div className="flex items-start gap-4">
                  {/* Action icon */}
                  <div className="p-3 bg-stone-50 rounded-lg">
                    <Icon className="w-6 h-6 text-amber-600" />
                  </div>
                  
                  <div className="flex-1">
                    {/* Timestamp and relative time */}
                    <div className="flex items-center gap-4 text-sm text-stone-500 mb-2">
                      <span>{formatTimestamp(event.timestamp)}</span>
                      <span className="text-stone-400">{formatRelativeTime(event.timestamp)}</span>
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
            </div>
          );
        })}
      </div>
    </div>
  );
};

const TableView = ({ events, isLoading, sortBy, sortOrder, onSort }) => {
  if (isLoading) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead className="bg-white">
            <tr className="border-b border-stone-200">
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Event</th>
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Actor</th>
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Action</th>
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Category</th>
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Status</th>
              <th className="px-6 py-4 text-left text-sm font-semibold text-stone-900">Timestamp</th>
            </tr>
          </thead>
          <tbody>
            {[...Array(5)].map((_, i) => (
              <tr key={i} className="border-b border-stone-100 animate-pulse">
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-32"></div></td>
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-24"></div></td>
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-20"></div></td>
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-24"></div></td>
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-20"></div></td>
                <td className="px-6 py-4"><div className="h-4 bg-stone-200 rounded w-32"></div></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  
  if (!events || events.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-16 h-16 mx-auto bg-stone-100 rounded-full flex items-center justify-center mb-4">
          <Table2 className="w-8 h-8 text-stone-500" />
        </div>
        <h3 className="text-lg font-semibold text-stone-900 mb-2">No events found</h3>
        <p className="text-stone-500">Try adjusting your filters</p>
      </div>
    );
  }
  
  const sortedEvents = [...events].sort((a, b) => {
    let aVal = a[sortBy] || '';
    let bVal = b[sortBy] || '';
    
    if (sortBy === 'timestamp') {
      aVal = new Date(a.timestamp);
      bVal = new Date(b.timestamp);
    }
    
    if (aVal < bVal) return sortOrder === 'asc' ? -1 : 1;
    if (aVal > bVal) return sortOrder === 'asc' ? 1 : -1;
    return 0;
  });
  
  const getSortIcon = (column) => {
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
              onClick={() => onSort('action')} 
              className="px-6 py-4 text-left text-sm font-semibold text-stone-900 cursor-pointer hover:bg-stone-50 flex items-center gap-1"
            >
              Action {getSortIcon('action')}
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
          {sortedEvents.map((event) => (
            <tr 
              key={event.id} 
              className="border-b border-stone-100 hover:bg-stone-50 transition-colors"
            >
              <td className="px-6 py-4">
                <div className="flex items-center gap-2">
                  {actionIcons[event.action] && (
                    <div className="p-1 bg-stone-50 rounded">
                      {React.createElement(actionIcons[event.action], { className: "w-4 h-4 text-amber-600" })}
                    </div>
                  )}
                  <span className="font-medium text-stone-900">{actionLabels[event.action] || event.action}</span>
                </div>
              </td>
              <td className="px-6 py-4 text-stone-600">{event.actor}</td>
              <td className="px-6 py-4 text-stone-600">{event.action}</td>
              <td className="px-6 py-4"><CategoryBadge category={event.category} /></td>
              <td className="px-6 py-4"><StatusBadge status={event.status} /></td>
              <td className="px-6 py-4 text-stone-500 text-sm whitespace-nowrap">
                {formatTimestamp(event.timestamp)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const CardsView = ({ events, isLoading }) => {
  if (isLoading) {
    return (
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {[...Array(6)].map((_, i) => (
          <div key={i} className="bg-white rounded-xl border border-stone-200 p-4 animate-pulse">
            <div className="h-4 bg-stone-200 rounded w-3/4 mb-3"></div>
            <div className="h-3 bg-stone-100 rounded w-1/2 mb-2"></div>
            <div className="h-3 bg-stone-100 rounded w-2/3"></div>
          </div>
        ))}
      </div>
    );
  }
  
  if (!events || events.length === 0) {
    return (
      <div className="text-center py-12">
        <div className="w-16 h-16 mx-auto bg-stone-100 rounded-full flex items-center justify-center mb-4">
          <Grid3X3 className="w-8 h-8 text-stone-500" />
        </div>
        <h3 className="text-lg font-semibold text-stone-900 mb-2">No events found</h3>
        <p className="text-stone-500">Try adjusting your filters</p>
      </div>
    );
  }
  
  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
      {events.map((event) => {
        const Icon = actionIcons[event.action] || MessageSquare;
        const label = actionLabels[event.action] || event.action;
        
        return (
          <div key={event.id} className="bg-white rounded-xl border border-stone-200 p-4 hover:shadow-lg transition-shadow">
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
              <span className="text-xs text-stone-400">{formatRelativeTime(event.timestamp)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
};

// Pagination Component
const Pagination = ({ currentPage, totalPages, onPageChange, isLoading }) => {
  if (totalPages <= 1) return null;
  
  return (
    <div className="flex items-center justify-between mt-6">
      <div className="flex items-center gap-2">
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage === 1 || isLoading}
          className="p-2 rounded-lg border border-stone-200 bg-white text-stone-600 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
        >
          <ChevronLeft className="w-5 h-5" />
        </button>
        <span className="text-sm text-stone-500">
          Page {currentPage} of {totalPages}
        </span>
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage === totalPages || isLoading}
          className="p-2 rounded-lg border border-stone-200 bg-white text-stone-600 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50"
        >
          <ChevronRight className="w-5 h-5" />
        </button>
      </div>
    </div>
  );
};

// Main Audit Log Page Component
const AuditLogPage = () => {
  // State
  const [view, setView] = useState('timeline');
  const [filters, setFilters] = useState({
    search: '',
    actor: '',
    action: '',
    category: '',
    days: 7,
  });
  const [sortBy, setSortBy] = useState('timestamp');
  const [sortOrder, setSortOrder] = useState('desc');
  const [page, setPage] = useState(1);
  const [refreshing, setRefreshing] = useState(false);
  
  const limit = 20;
  
  // React Query to fetch data
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['audit-logs', filters, page, sortBy, sortOrder],
    queryFn: () => fetchAuditLogs({
      ...filters,
      limit,
      offset: (page - 1) * limit,
      sort_by: sortBy,
      sort_order: sortOrder
    }),
    keepPreviousData: true,
  });
  
  // Handle filter changes
  const handleFilterChange = (name, value) => {
    setFilters(prev => ({ ...prev, [name]: value }));
    setPage(1); // Reset to first page when filters change
  };
  
  // Handle preset selection
  const handlePresetSelect = (presetFilters) => {
    setFilters(prev => ({ ...prev, ...presetFilters }));
    setPage(1);
  };
  
  // Handle sort
  const handleSort = (column) => {
    if (sortBy === column) {
      setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc');
    } else {
      setSortBy(column);
      setSortOrder('desc');
    }
  };
  
  // Handle refresh
  const handleRefresh = () => {
    setRefreshing(true);
    refetch().then(() => setRefreshing(false));
  };
  
  // Handle export
  const handleExport = (format) => {
    const query = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== '' && value !== undefined) {
        query.set(key, String(value));
      }
    });
    query.set('format', format);
    
    window.open(`/api/audit-logs/export?${query.toString()}`, '_blank');
  };
  
  // Calculate total pages
  const totalPages = data ? Math.ceil(data.total / limit) : 0;
  
  return (
    <div className="min-h-screen bg-stone-50">
      {/* Header */}
      <header className="bg-white border-b border-stone-200 sticky top-0 z-10">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div>
              <h1 className="text-2xl font-bold text-stone-900">Audit Log</h1>
              <p className="text-sm text-stone-500">Track system activity and events</p>
            </div>
          </div>
        </div>
      </header>
      
      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
        {/* Top Toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-4">
            <ViewToggle view={view} onChange={setView} />
            <div className="text-sm text-stone-500">
              Showing {view === 'cards' ? 'grid' : view} view
            </div>
          </div>
          
          <div className="flex items-center gap-3">
            <PresetDropdown onSelect={handlePresetSelect} />
            <ExportDropdown onExport={handleExport} isLoading={isLoading} />
            <button
              onClick={handleRefresh}
              disabled={isLoading || refreshing}
              className="p-2 rounded-lg border border-stone-200 bg-white text-stone-600 disabled:opacity-50 disabled:cursor-not-allowed hover:bg-stone-50 flex items-center gap-2"
            >
              {refreshing ? (
                <RefreshCw className="w-4 h-4 animate-spin" />
              ) : (
                <>
                  <RefreshCw className="w-4 h-4" />
                  <span className="text-sm font-medium">Refresh</span>
                </>
              )}
            </button>
          </div>
        </div>
        
        {/* Filter Bar */}
        <div className="bg-white rounded-xl border border-stone-200 p-6 mb-6">
          <div className=" grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
            <SearchInput
              value={filters.search}
              onChange={(value) => handleFilterChange('search', value)}
              placeholder="Search events..."
            />
            
            <SelectInput
              value={filters.actor}
              onChange={(value) => handleFilterChange('actor', value)}
              options={[
                { value: '', label: 'All Actors' },
                { value: 'admin1', label: 'admin1' },
                { value: 'System', label: 'System' },
                { value: 'Bot', label: 'Bot' },
              ]}
              label="Actor"
            />
            
            <SelectInput
              value={filters.action}
              onChange={(value) => handleFilterChange('action', value)}
              options={actionOptions}
              label="Action"
            />
            
            <SelectInput
              value={filters.category}
              onChange={(value) => handleFilterChange('category', value)}
              options={categoryOptions}
              label="Category"
            />
            
            <DateRangeSelect
              value={filters.days}
              onChange={(value) => handleFilterChange('days', value)}
            />
          </div>
          
          {/* Quick filter apply/clear */}
          <div className="flex justify-end mt-4">
            <button
              onClick={() => setFilters({
                search: '',
                actor: '',
                action: '',
                category: '',
                days: 7,
              })}
              className="text-sm text-amber-600 hover:text-amber-700 flex items-center gap-1"
            >
              <X className="w-4 h-4" />
              Clear Filters
            </button>
          </div>
        </div>
        
        {/* Results Summary */}
        {data && (
          <div className="mb-4 text-sm text-stone-500">
            Showing {data.offset + 1}-{Math.min(data.offset + data.events.length, data.total)} of {data.total} events
            {data.date_range && (
              <span className="ml-4">
                ({format(new Date(data.date_range.start_date), 'MMM dd, yyyy')} to {format(new Date(data.date_range.end_date), 'MMM dd, yyyy')})
              </span>
            )}
          </div>
        )}
        
        {/* Error State */}
        {isError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-red-700">
            Failed to load audit logs. Please try again.
          </div>
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
            onSort={handleSort}
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
      </main>
    </div>
  );
};

export default AuditLogPage;