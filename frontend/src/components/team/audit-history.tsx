
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
          <h3 className="text-lg font-semibold text-slate-200">{date} <span className="text-xs font-normal text-slate-500">{dateEvents.length} events</span></h3>
          <div className="space-y-3 border-l border-slate-700 pl-4">
            {dateEvents.map(event => (
              <Card key={event.id}>
                <CardHeader title={LABELS[event.action] || event.action.replace(/_/g, ' ')} description={`${event.actor_label || event.actor_username || 'System'}${event.actor_role ? ` · ${event.actor_role}` : ''} · ${relativeTime(event.created_at)}`} actions={<Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>} />
                <CardBody className="space-y-3">
                  <div className="flex flex-wrap gap-3 text-xs text-slate-400">
                    <span>Tenant: {event.tenant_name || event.tenant_id || 'Platform'}{event.tenant_slug ? ` · ${event.tenant_slug}` : ''}</span>
                    <span>IP: {event.ip_address || '—'}</span>
                    <span>Resource: {event.resource_type || '—'}{event.resource_id ? `/${event.resource_id}` : ''}</span>
                  </div>
                  <AuditEventDetails event={event} />
                </CardBody>
              </Card>
            ))}
          </div>
        </section>
      ))}
    </div>
  )
}

export function AuditHistory() {
  const [filters, setFilters] = useState<AuditFiltersExtended>({ limit: PAGE_SIZE, offset: 0, sort_by: 'created_at', sort_order: 'desc' })
  const [draft, setDraft] = useState({
    search: '', actor: '', action: '', category: '', tenant_id: '', outcome: '' as AuditOutcome | '',
    start_date: '', end_date: '', preset: 'last_7_days' as FilterPreset,
  })
  const [viewMode, setViewMode] = useState<ViewMode>('table')
  const [selectedEvents, setSelectedEvents] = useState<Set<number>>(new Set())
  const [showRefreshing, setShowRefreshing] = useState(false)
  const [toastMessage, setToastMessage] = useState<string | null>(null)
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false)
  const [showStats, setShowStats] = useState(false)
  const [showCustomDateRange, setShowCustomDateRange] = useState(false)

  useEffect(() => {
    const savedFilters = loadFiltersFromStorage()
    if (savedFilters) setDraft(prev => ({ ...prev, ...savedFilters }))
  }, [])

  const requestFilters = useMemo(() => ({ ...filters, limit: filters.limit ?? PAGE_SIZE }), [filters])
  const state = useAsync(() => auditApiExtended.list(requestFilters) as Promise<AuditPageState>, [JSON.stringify(requestFilters)])
  const page = state.data
  const events = page?.events ?? []
  const formattedEvents = useMemo(() => events.map(formatEventForDisplay), [events])
  const start = page && page.total ? page.offset + 1 : 0
  const end = page ? page.offset + page.events.length : 0
  const statistics = useAsync(() => auditApiExtended.getStatistics(filters) as Promise<AuditStatistics>, [JSON.stringify(filters)])

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

  const debouncedSearch = useMemo(() => debounce((value: string) => {
    setDraft(prev => ({ ...prev, search: value }))
    applyFilters({ ...draft, search: value })
  }, 300), [applyFilters, draft])

  const handleSort = (column: string) => setFilters(current => ({
    ...current,
    sort_by: column || 'created_at',
    sort_order: current.sort_by === column && current.sort_order === 'desc' ? 'asc' : 'desc',
    offset: 0,
  }))

  const updateDraft = <K extends keyof typeof draft>(key: K, value: (typeof draft)[K]) => setDraft(current => ({ ...current, [key]: value }))
  const clearFilters = () => {
    const clean = { search: '', actor: '', action: '', category: '', tenant_id: '', outcome: '' as AuditOutcome | '', start_date: '', end_date: '', preset: 'last_7_days' as FilterPreset }
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
      <PageHeader title="Audit History" description="Review administrator activity across tenants, with actor, client, request and change details." actions={
        <div className="flex flex-wrap gap-2">
          <FilterPresets onApplyPreset={applyPreset} />
          <ExportMenu events={formattedEvents} filters={filters} onExportSuccess={notifyExport} />
          <Button variant="secondary" icon={<RefreshCw className={`h-4 w-4 ${showRefreshing ? 'animate-spin' : ''}`} />} onClick={refresh}>Refresh</Button>
        </div>
      } />
      {toastMessage && <Toast message={toastMessage} />}
      {state.error && <Alert tone="danger" title="Could not load audit history">{state.error}</Alert>}
      {state.loading && <LoadingBlock label="Loading audit history..." />}

      <Card>
        <CardHeader title="Filters" description="Search actors, clients, IP addresses, user agents and safe event details." actions={<Button size="sm" variant="ghost" onClick={() => setShowAdvancedFilters(v => !v)}>{showAdvancedFilters ? 'Hide' : 'More'} filters</Button>} />
        <CardBody className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Input label="Search" placeholder="Filename, IP, actor, change..." value={draft.search} onChange={e => { updateDraft('search', e.target.value); debouncedSearch(e.target.value) }} />
            <Input label="Actor" placeholder="Username" value={draft.actor} onChange={e => updateDraft('actor', e.target.value)} />
            <Select label="Action" value={draft.action} onChange={e => updateDraft('action', e.target.value)}><option value="">All actions</option>{Object.entries(LABELS).map(([action, label]) => <option key={action} value={action}>{label}</option>)}</Select>
            <Select label="Outcome" value={draft.outcome} onChange={e => updateDraft('outcome', e.target.value as AuditOutcome | '')}><option value="">All outcomes</option><option value="success">Success</option><option value="failure">Failure</option></Select>
          </div>
          {showAdvancedFilters && <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <Select label="Category" value={draft.category} onChange={e => updateDraft('category', e.target.value)}><option value="">All categories</option>{Object.entries(ACTION_CATEGORIES).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</Select>
            <Input label="Tenant / client ID" placeholder="Tenant ID" value={draft.tenant_id} onChange={e => updateDraft('tenant_id', e.target.value)} />
            <DateRangePicker startDate={draft.start_date} endDate={draft.end_date} preset={draft.preset} onChange={(preset, start_date = '', end_date = '') => setDraft(current => ({ ...current, preset, start_date, end_date }))} />
            <div className="flex items-end gap-2"><Button variant="primary" onClick={() => applyFilters()}>Apply filters</Button><Button variant="ghost" onClick={clearFilters}>Clear</Button></div>
          </div>}
          {!showAdvancedFilters && <div className="flex flex-wrap items-center gap-2"><span className="text-xs text-slate-500">Date range</span>{(['today', 'last_7_days', 'last_30_days', 'last_90_days'] as FilterPreset[]).map(preset => <Button key={preset} size="sm" variant={draft.preset === preset ? 'primary' : 'secondary'} onClick={() => { const dates = getPresetDates(preset); const next = { ...draft, preset, ...dates }; setDraft(next); applyFilters(next) }}>{preset.replace(/_/g, ' ')}</Button>)}</div>}
        </CardBody>
      </Card>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2"><Button size="sm" variant={viewMode === 'table' ? 'primary' : 'secondary'} icon={<Table2 className="h-4 w-4" />} onClick={() => setViewMode('table')}>Table</Button><Button size="sm" variant={viewMode === 'cards' ? 'primary' : 'secondary'} icon={<Grid3X3 className="h-4 w-4" />} onClick={() => setViewMode('cards')}>Cards</Button><Button size="sm" variant={viewMode === 'timeline' ? 'primary' : 'secondary'} icon={<LineChart className="h-4 w-4" />} onClick={() => setViewMode('timeline')}>Timeline</Button></div>
        <Button size="sm" variant="ghost" onClick={() => setShowStats(v => !v)}>{showStats ? 'Hide' : 'Show'} summary</Button>
      </div>
      {showStats && statistics.data && <StatisticsView statistics={statistics.data} events={formattedEvents} />}

      {page?.events.length === 0 && !state.loading && <Card><CardBody><EmptyState title="No activity found" description="Try changing the filters or date range." /></CardBody></Card>}
      {page && page.events.length > 0 && <>
        <div className="flex items-center justify-between text-xs text-slate-500"><span>Showing {start}–{end} of {page.total.toLocaleString()} events</span><span>Sort: {filters.sort_by || 'Date'} ({filters.sort_order})</span></div>
        {viewMode === 'table' && <TableView events={formattedEvents} sortBy={filters.sort_by || ''} sortOrder={filters.sort_order || 'desc'} onSort={handleSort} />}
        {viewMode === 'cards' && <div className="space-y-3">{formattedEvents.map(event => <Card key={event.id}><CardHeader title={LABELS[event.action] || event.action.replace(/_/g, ' ')} description={`${event.actor_label || event.actor_username || 'System'}${event.actor_role ? ` · ${event.actor_role}` : ''} · ${formatDate(event.created_at)}`} actions={<Badge tone={event.outcome === 'success' ? 'success' : 'danger'}>{event.outcome}</Badge>} /><CardBody><AuditEventDetails event={event} /></CardBody></Card>)}</div>}
        {viewMode === 'timeline' && <TimelineView events={formattedEvents} />}
        <div className="mt-4 flex items-center justify-between"><Button variant="secondary" disabled={page.offset === 0 || state.loading} icon={<ChevronLeft className="h-4 w-4" />} onClick={() => setFilters(v => ({ ...v, offset: Math.max(0, (v.offset ?? 0) - PAGE_SIZE) }))}>Previous</Button><span className="text-xs text-slate-500">Page {Math.floor(page.offset / page.limit) + 1} of {Math.max(1, Math.ceil(page.total / page.limit))}</span><Button variant="secondary" disabled={page.offset + page.events.length >= page.total || state.loading} icon={<ChevronRight className="h-4 w-4" />} onClick={() => setFilters(v => ({ ...v, offset: (v.offset ?? 0) + PAGE_SIZE }))}>Next</Button></div>
      </>}
    </div>
  )
}

export type { ViewMode, FilterPreset } from './audit-history.types'
