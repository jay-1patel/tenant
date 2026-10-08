import { useMemo, useState, type ChangeEvent } from 'react'
import {
  AlertTriangle,
  Layers,
  Lock,
  Pencil,
  Plus,
  Search,
  Settings2,
  Trash2,
  Upload,
  X,
} from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { contentWritePerms } from '@/lib/permissions'
import { offeringsApi } from '@/lib/offerings'
import { uploadRecordImage } from '@/lib/uploads'
import { useTenants } from '@/lib/tenants'
import { getVertical } from '@/lib/verticals'
import type { Offering, OfferingInput, RecordColumn, RecordColumnType } from '@/lib/types'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Checkbox, Switch } from '@/components/ui/switch'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

/** Mirrors `shared/tenancy/records.py` COLUMN_TYPES for the column editor. */
const COLUMN_TYPE_OPTIONS: { value: RecordColumnType; label: string; hint: string }[] = [
  { value: 'text', label: 'Text', hint: 'Short free text.' },
  { value: 'long_text', label: 'Long text', hint: 'Multi-line, e.g. an itinerary.' },
  { value: 'number', label: 'Number', hint: 'Any number, stored with decimals.' },
  { value: 'integer', label: 'Whole number', hint: 'Counts, days, max travellers.' },
  { value: 'boolean', label: 'Yes / no', hint: 'A tick box.' },
  { value: 'date', label: 'Date', hint: 'YYYY-MM-DD.' },
  { value: 'select', label: 'Pick from a list', hint: 'You supply the choices.' },
]

/** System columns map straight onto the offering record; the rest go in `values`. */
const SYSTEM_FIELDS = new Set([
  'name',
  'category',
  'short_label',
  'short_description',
  'description',
  'price',
  'detail_url',
  'media_url',
  'is_active',
])

function cellValue(row: Offering, column: RecordColumn): string | number | boolean | null {
  if (SYSTEM_FIELDS.has(column.key)) {
    const value = (row as unknown as Record<string, unknown>)[column.key]
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return value
    return null
  }
  return row.values?.[column.key] ?? null
}

function displayCell(value: string | number | boolean | null): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  return String(value)
}

/**
 * The tenant's records, as a table whose columns the admin owns.
 *
 * Every vertical gets a different table — SKU and size for a shop, itinerary and
 * max travellers for a travel company. Adding a column here is a real database
 * change (`ALTER TABLE products`), which is why schema edits need
 * `manage_operations` while day-to-day row edits need only
 * `edit_delete_products`.
 */
export function RecordsPanel({ tenantId }: { tenantId: string }) {
  const { active } = useTenants()
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()

  const content = getVertical(active?.vertical).content
  const canRead = can('view_products')
  // Add/edit/remove are granted separately per vertical — see contentWritePerms.
  const { add: addPerms, edit: editPerms, remove: removePerms } = contentWritePerms(active?.vertical)
  const canAdd = addPerms.some(can)
  const canEditRow = editPerms.some(can)
  const canRemove = removePerms.some(can)
  const canEdit = canAdd || canEditRow || canRemove
  const canSchema = can('manage_operations')

  const [showInactive, setShowInactive] = useState(false)
  const [search, setSearch] = useState('')
  const [category, setCategory] = useState('')

  const state = useAsync(
    (signal) => offeringsApi.listDetailed(tenantId, { includeInactive: showInactive }, signal),
    [tenantId, showInactive],
  )
  const columns = state.data?.columns ?? []
  const rows = state.data?.offerings ?? []

  const [editing, setEditing] = useState<Offering | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)
  const [columnForm, setColumnForm] = useState<{ column: RecordColumn | null } | null>(null)

  const categories = useMemo(
    () => [...new Set(rows.map((r) => r.category).filter(Boolean))].sort((a, b) => a.localeCompare(b)),
    [rows],
  )

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return rows.filter((row) => {
      if (category && row.category !== category) return false
      if (!q) return true
      const haystack = [
        row.name,
        row.category,
        row.short_description,
        ...Object.values(row.values ?? {}).map((v) => (v == null ? '' : String(v))),
      ]
        .join(' ')
        .toLowerCase()
      return haystack.includes(q)
    })
  }, [rows, search, category])

  const reload = state.reload

  const removeRow = async (id: number, hard: boolean) => {
    const result = await action.run(() => offeringsApi.remove(tenantId, id, hard))
    if (result) {
      setConfirmDelete(null)
      reload()
      toast.push(hard ? 'Deleted permanently' : 'Removed — the bot will not list it again')
    }
  }

  const dropColumn = async (column: RecordColumn) => {
    const result = await action.run(() => offeringsApi.deleteColumn(tenantId, column.key))
    if (result) {
      toast.push(`‘${column.label}’ ${result.database_column_dropped ? 'and its column were' : 'was'} removed`)
      reload()
    }
  }

  if (!canRead) {
    return (
      <div>
        <PageHeader title={content.label} description="What this tenant sells, offers or lists." />
        <Alert tone="warning" title="Not permitted">
          Viewing {content.label.toLowerCase()} needs the <strong>view_products</strong> permission.
        </Alert>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title={content.label}
        description={`A table the bot reads from. Its columns are this tenant's own — add a ${content.singular} column the business needs and the bot can answer with it.`}
        actions={
          <div className="flex items-center gap-2">
            {canRead && (
              <Button
                variant="ghost"
                icon={<Settings2 className="h-4 w-4" />}
                disabled={!canSchema}
                title={canSchema ? 'Add a column' : 'Needs manage_operations'}
                onClick={() => setColumnForm({ column: null })}
              >
                Add column
              </Button>
            )}
            {canAdd && (
              <Button
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                disabled={creating || editing !== null}
                onClick={() => setCreating(true)}
              >
                Add a {content.singular}
              </Button>
            )}
          </div>
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      {columnForm && (
        <ColumnForm
          initial={columnForm.column}
          busy={action.busy}
          onCancel={() => setColumnForm(null)}
          onSubmit={async (body) => {
            const result = columnForm.column
              ? await action.run(() =>
                  offeringsApi.updateColumn(tenantId, columnForm.column!.key, body),
                )
              : await action.run(() => offeringsApi.createColumn(tenantId, body))
            if (result) {
              setColumnForm(null)
              reload()
              toast.push(columnForm.column ? 'Column updated' : 'Column added')
            }
          }}
        />
      )}

      {creating && (
        <RecordForm
          tenantId={tenantId}
          columns={columns}
          content={content}
          busy={action.busy}
          onCancel={() => setCreating(false)}
          onSubmit={async (body) => {
            const result = await action.run(() => offeringsApi.create(tenantId, body))
            if (result) {
              setCreating(false)
              reload()
              toast.push(`${result.name} added`)
            }
          }}
        />
      )}

      {editing && (
        <RecordForm
          tenantId={tenantId}
          columns={columns}
          content={content}
          initial={editing}
          busy={action.busy}
          onCancel={() => setEditing(null)}
          onSubmit={async (body) => {
            const result = await action.run(() => offeringsApi.update(tenantId, editing.id, body))
            if (result) {
              setEditing(null)
              reload()
              toast.push('Saved')
            }
          }}
        />
      )}

      <Card className="mt-4">
        <CardHeader
          title={`${filtered.length} ${filtered.length === 1 ? content.singular : content.label.toLowerCase()}`}
          icon={<Layers className="h-4 w-4" />}
          actions={
            <div className="flex items-center gap-3">
              <div className="relative w-48">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search…"
                  className="w-full rounded-lg bg-surface-raised py-1.5 pl-8 pr-3 text-xs text-slate-100 placeholder:text-slate-500 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
                />
              </div>
              {categories.length > 1 && (
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className="rounded-lg bg-surface-raised px-2 py-1.5 text-xs text-slate-200 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
                >
                  <option value="">All groups</option>
                  {categories.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              )}
              <div className="w-40">
                <Switch size="sm" checked={showInactive} onChange={setShowInactive} label="Show removed" />
              </div>
            </div>
          }
        />

        {state.loading ? (
          <LoadingBlock label={`Loading ${content.label.toLowerCase()}…`} />
        ) : state.error ? (
          <CardBody>
            <Alert tone="danger" title="Could not load">
              {state.error}
            </Alert>
          </CardBody>
        ) : rows.length === 0 ? (
          <EmptyState
            title={`No ${content.label.toLowerCase()} yet`}
            description={
              canEdit
                ? `Add the first ${content.singular} and the bot can start answering questions about it.`
                : 'Nothing has been added for this tenant yet.'
            }
            icon={<Layers className="h-6 w-6" />}
            action={
              canSchema ? (
                <Button
                  variant="secondary"
                  icon={<Settings2 className="h-4 w-4" />}
                  onClick={() => setColumnForm({ column: null })}
                >
                  Shape the columns
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-max text-left text-sm">
              <thead>
                <tr className="border-b border-surface-line">
                  {columns.map((column) => (
                    <th key={column.key} className="whitespace-nowrap px-4 py-2.5 align-bottom">
                      <div className="flex items-center gap-1.5">
                        <span className="text-2xs font-semibold uppercase tracking-wider text-slate-400">
                          {column.label}
                        </span>
                        {column.is_system ? (
                          <Lock className="h-3 w-3 text-slate-600" />
                        ) : canSchema ? (
                          <span className="flex items-center">
                            <button
                              type="button"
                              title="Edit column"
                              onClick={() => setColumnForm({ column })}
                              className="rounded p-0.5 text-slate-500 transition hover:bg-accent-50 hover:text-slate-100"
                            >
                              <Pencil className="h-3 w-3" />
                            </button>
                            <button
                              type="button"
                              title="Delete column and its data"
                              onClick={() => dropColumn(column)}
                              className="rounded p-0.5 text-slate-500 transition hover:bg-accent-50 hover:text-rose-700"
                            >
                              <Trash2 className="h-3 w-3" />
                            </button>
                          </span>
                        ) : null}
                      </div>
                    </th>
                  ))}
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-surface-line">
                {filtered.map((row) => (
                  <tr key={row.id} className="align-top">
                    {columns.map((column) => (
                      <td key={column.key} className="px-4 py-3 text-slate-200">
                        {column.key === 'name' ? (
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="font-medium text-slate-100">{row.name}</span>
                            {!row.is_active && <Badge tone="neutral">removed</Badge>}
                          </div>
                        ) : column.key === 'short_label' && row.short_label ? (
                          <Badge tone="accent">{row.short_label}</Badge>
                        ) : (
                          <span className={cn(column.type === 'long_text' && 'block max-w-xs truncate')}>
                            {displayCell(cellValue(row, column))}
                          </span>
                        )}
                      </td>
                    ))}
                    <td className="px-4 py-3">
                      {(canEditRow || canRemove) && (
                        <div className="flex shrink-0 items-center justify-end gap-2">
                          {canEditRow && (
                            <Button
                              size="sm"
                              variant="secondary"
                              icon={<Pencil className="h-3.5 w-3.5" />}
                              onClick={() => setEditing(row)}
                            >
                              Edit
                            </Button>
                          )}
                          {canRemove && row.is_active &&
                            (confirmDelete === row.id ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="danger"
                                  loading={action.busy}
                                  onClick={() => removeRow(row.id, true)}
                                >
                                  Delete forever
                                </Button>
                                <Button size="sm" variant="ghost" onClick={() => setConfirmDelete(null)}>
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={<Trash2 className="h-3.5 w-3.5" />}
                                onClick={() => setConfirmDelete(row.id)}
                              >
                                Remove
                              </Button>
                            ))}
                          {canEditRow && !row.is_active && (
                            <Button
                              size="sm"
                              variant="ghost"
                              loading={action.busy}
                              onClick={() =>
                                action
                                  .run(() => offeringsApi.update(tenantId, row.id, { is_active: true }))
                                  .then((r) => r && reload())
                              }
                            >
                              Restore
                            </Button>
                          )}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      {canSchema && (
        <p className="mt-3 flex items-center gap-1.5 text-xs text-slate-500">
          <AlertTriangle className="h-3.5 w-3.5" />
          Deleting a column drops its data. Core columns (name, price, …) are always kept.
        </p>
      )}
    </div>
  )
}

// ── column editor ───────────────────────────────────────────────────────────

function ColumnForm({
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  initial: RecordColumn | null
  busy: boolean
  onSubmit: (body: {
    key: string
    label: string
    type: RecordColumnType
    required: boolean
    options: string[]
    help: string
  }) => void
  onCancel: () => void
}) {
  const [key, setKey] = useState(initial?.key ?? '')
  const [label, setLabel] = useState(initial?.label ?? '')
  const [type, setType] = useState<RecordColumnType>(initial?.type ?? 'text')
  const [required, setRequired] = useState(initial?.required ?? false)
  const [options, setOptions] = useState((initial?.options ?? []).join(', '))
  const [help, setHelp] = useState(initial?.help ?? '')

  const typeHint = COLUMN_TYPE_OPTIONS.find((t) => t.value === type)?.hint

  return (
    <Card className="mt-4">
      <CardHeader
        title={initial ? `Edit the ‘${initial.label}’ column` : 'Add a column'}
        description="A column is a field on every record — a SKU, a destination, a duration."
        actions={
          <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} onClick={onCancel}>
            Close
          </Button>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Column name"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Destination"
            hint="The header the admin and the bot see."
          />
          <Input
            label="Key"
            value={key}
            disabled={Boolean(initial)}
            onChange={(e) => setKey(e.target.value)}
            placeholder="destination"
            hint="lower-case, underscores; cannot be changed later."
          />
        </div>

        <div>
          <label className="field-label">Type</label>
          <select
            value={type}
            onChange={(e) => setType(e.target.value as RecordColumnType)}
            className="w-full rounded-lg bg-surface-raised px-3 py-2 text-sm text-slate-100 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
          >
            {COLUMN_TYPE_OPTIONS.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
          {typeHint && <p className="hint">{typeHint}</p>}
        </div>

        {type === 'select' && (
          <Input
            label="Choices"
            value={options}
            onChange={(e) => setOptions(e.target.value)}
            placeholder="Fixed price, Time and materials, Retainer"
            hint="Comma-separated."
          />
        )}

        <Input label="Help text" value={help} onChange={(e) => setHelp(e.target.value)} placeholder="Optional note shown under the field." />

        <Checkbox checked={required} onChange={setRequired} label="Required" description="A record cannot be saved without it." />

        <div className="flex items-center gap-2">
          <Button
            variant="primary"
            loading={busy}
            onClick={() =>
              onSubmit({
                key: (initial?.key ?? key).trim().toLowerCase(),
                label: label.trim() || key.trim(),
                type,
                required,
                options: options
                  .split(',')
                  .map((s) => s.trim())
                  .filter(Boolean),
                help: help.trim(),
              })
            }
          >
            {initial ? 'Save column' : 'Add column'}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}

// ── record editor ───────────────────────────────────────────────────────────

type Cells = Record<string, string | boolean>

function initialCells(columns: RecordColumn[], row?: Offering): Cells {
  const cells: Cells = {}
  for (const column of columns) {
    if (column.type === 'boolean') {
      // A new record defaults to visible; every other boolean column
      // (returnable, includes_flight…) defaults to off.
      cells[column.key] = Boolean(row ? cellValue(row, column) : column.key === 'is_active')
    } else {
      const value = row ? cellValue(row, column) : null
      cells[column.key] = value === null || value === undefined ? '' : String(value)
    }
  }
  return cells
}

function RecordForm({
  tenantId,
  columns,
  content,
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  tenantId: string
  columns: RecordColumn[]
  content: ReturnType<typeof getVertical>['content']
  initial?: Offering
  busy: boolean
  onSubmit: (body: OfferingInput) => void
  onCancel: () => void
}) {
  const [cells, setCells] = useState<Cells>(() => initialCells(columns, initial))
  const [touched, setTouched] = useState(false)
  const [imageBusy, setImageBusy] = useState(false)
  const [imageError, setImageError] = useState<string | null>(null)

  const set = (key: string, value: string | boolean) => setCells((c) => ({ ...c, [key]: value }))
  const nameColumn = columns.find((c) => c.key === 'name')
  const nameMissing = touched && nameColumn && !String(cells.name ?? '').trim()

  const pickImage = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!file.type.startsWith('image/')) {
      setImageError('Only image files (PNG, JPG, WebP…) can be uploaded.')
      return
    }
    setImageBusy(true)
    setImageError(null)
    try {
      const url = await uploadRecordImage(tenantId, file)
      set('media_url', url)
    } catch (err) {
      setImageError(err instanceof Error ? err.message : 'The upload failed.')
    } finally {
      setImageBusy(false)
    }
  }

  const submit = () => {
    setTouched(true)
    if (nameMissing) return

    const top: Record<string, unknown> = {}
    const values: Record<string, string | boolean> = {}
    for (const column of columns) {
      const value = cells[column.key]
      if (SYSTEM_FIELDS.has(column.key)) top[column.key] = value
      else values[column.key] = value
    }

    onSubmit({
      name: String(top.name ?? '').trim(),
      category: String(top.category ?? '').trim() || 'general',
      short_label: String(top.short_label ?? '').trim(),
      short_description: String(top.short_description ?? '').trim(),
      description: String(top.description ?? '').trim(),
      price: String(top.price ?? '').trim() || null,
      detail_url: String(top.detail_url ?? '').trim(),
      media_url: String(top.media_url ?? '').trim(),
      media_type: 'image',
      attrs: initial?.attrs ?? {},
      values,
      sort_order: initial?.sort_order ?? 0,
      is_active: Boolean(top.is_active),
    })
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title={initial ? `Edit ${initial.name}` : `Add a ${content.singular}`}
        description="The fields are this tenant's columns — the same ones shown in the table."
        actions={
          <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} onClick={onCancel}>
            Close
          </Button>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          {columns.map((column) => {
            const value = cells[column.key]
            if (column.type === 'long_text') {
              return (
                <div key={column.key} className="sm:col-span-2">
                  <Textarea
                    label={column.label}
                    rows={3}
                    value={String(value ?? '')}
                    hint={column.help || undefined}
                    error={column.key === 'name' && nameMissing ? 'A name is required' : undefined}
                    onChange={(e) => set(column.key, e.target.value)}
                  />
                </div>
              )
            }
            if (column.type === 'boolean') {
              return (
                <div key={column.key} className="flex items-center pt-6">
                  <Checkbox
                    checked={Boolean(value)}
                    onChange={(next) => set(column.key, next)}
                    label={column.label}
                    description={column.help || undefined}
                  />
                </div>
              )
            }
            if (column.type === 'select') {
              return (
                <div key={column.key}>
                  <label className="field-label">{column.label}</label>
                  <select
                    value={String(value ?? '')}
                    onChange={(e) => set(column.key, e.target.value)}
                    className="w-full rounded-lg bg-surface-raised px-3 py-2 text-sm text-slate-100 ring-1 ring-inset ring-surface-line focus:outline-none focus:ring-2 focus:ring-accent-500"
                  >
                    <option value="">—</option>
                    {column.options.map((option) => (
                      <option key={option} value={option}>
                        {option}
                      </option>
                    ))}
                  </select>
                  {column.help && <p className="hint">{column.help}</p>}
                </div>
              )
            }
            if (column.key === 'media_url') {
              const url = String(value ?? '')
              return (
                <div key={column.key}>
                  <label className="field-label">{column.label}</label>
                  {url ? (
                    <div className="flex items-center gap-2.5 rounded-lg bg-surface-raised p-2 ring-1 ring-inset ring-surface-line">
                      <img
                        src={url}
                        alt=""
                        className="h-10 w-10 shrink-0 rounded object-cover ring-1 ring-inset ring-surface-line"
                      />
                      <span className="min-w-0 flex-1 truncate text-xs text-slate-500">{url}</span>
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={<Trash2 className="h-3.5 w-3.5" />}
                        onClick={() => set('media_url', '')}
                      >
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <label
                      className={cn(
                        'flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-surface-raised py-2 text-sm text-slate-300 ring-1 ring-inset ring-surface-line transition hover:bg-accent-50 hover:text-slate-100',
                        imageBusy && 'pointer-events-none opacity-60',
                      )}
                    >
                      <input
                        type="file"
                        accept="image/*"
                        className="hidden"
                        disabled={imageBusy}
                        onChange={pickImage}
                      />
                      <Upload className="h-4 w-4" />
                      {imageBusy ? 'Uploading…' : 'Upload image'}
                    </label>
                  )}
                  {imageError && <p className="hint text-rose-700">{imageError}</p>}
                  {column.help && !imageError && <p className="hint">{column.help}</p>}
                </div>
              )
            }
            return (
              <Input
                key={column.key}
                label={column.label}
                type={column.type === 'date' ? 'date' : column.type === 'number' || column.type === 'integer' ? 'number' : 'text'}
                value={String(value ?? '')}
                required={column.required && column.key !== 'name'}
                hint={column.help || undefined}
                error={column.key === 'name' && nameMissing ? 'A name is required' : undefined}
                onChange={(e) => set(column.key, e.target.value)}
              />
            )
          })}
        </div>

        <div className="flex items-center gap-2">
          <Button variant="primary" loading={busy} onClick={submit}>
            {initial ? 'Save changes' : `Add ${content.singular}`}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
