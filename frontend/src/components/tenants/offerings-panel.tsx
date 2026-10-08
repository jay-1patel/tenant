import { useMemo, useState } from 'react'
import { Layers, Package, Pencil, Plus, Trash2, X } from 'lucide-react'
import { useAction } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { contentWritePerms } from '@/lib/permissions'
import { offeringsApi, useOfferings } from '@/lib/offerings'
import { useTenants } from '@/lib/tenants'
import { getVertical } from '@/lib/verticals'
import type { Offering, OfferingInput } from '@/lib/types'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

/**
 * The tenant's content panel: what the bot can list, describe and quote.
 *
 * One record shape for every vertical, so this screen only changes its
 * vocabulary — "Services" and a tech stack for a software tenant, "Packages" and
 * an itinerary for a travel tenant. Rows are tenant-owned on the server: the
 * tenant is a path segment and a token for another tenant is refused.
 */
export function OfferingsPanel({ tenantId }: { tenantId: string }) {
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

  const [showInactive, setShowInactive] = useState(false)
  const { offerings, loading, error, reload } = useOfferings(tenantId, showInactive)
  const [editing, setEditing] = useState<Offering | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<number | null>(null)

  const groups = useMemo(() => {
    const map = new Map<string, Offering[]>()
    for (const item of offerings) {
      const key = item.category || 'Uncategorised'
      const bucket = map.get(key)
      if (bucket) bucket.push(item)
      else map.set(key, [item])
    }
    return [...map.entries()].sort((a, b) => a[0].localeCompare(b[0]))
  }, [offerings])

  const remove = async (id: number, hard: boolean) => {
    const result = await action.run(() => offeringsApi.remove(tenantId, id, hard))
    if (result) {
      setConfirmDelete(null)
      reload()
      toast.push(hard ? 'Deleted permanently' : 'Removed — the bot will not list it again')
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
        description={`Add, edit and delete what ${active?.display_name || 'this tenant'} offers. The bot answers from these — a ${content.singular} listed here is one the bot can describe, price and quote.`}
        actions={
          canAdd ? (
            <Button
              variant="primary"
              icon={<Plus className="h-4 w-4" />}
              disabled={creating || editing !== null}
              onClick={() => setCreating(true)}
            >
              Add a {content.singular}
            </Button>
          ) : undefined
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}
      {!canEdit && (
        <Alert tone="warning" title="Read-only" className="mb-4">
          Adding, editing and deleting needs the catalogue write permissions for
          this tenant's vertical.
        </Alert>
      )}

      {creating && (
        <OfferingForm
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
        <OfferingForm
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
          title={`${offerings.length} ${offerings.length === 1 ? content.singular : content.label.toLowerCase()}`}
          icon={<Package className="h-4 w-4" />}
          actions={
            <div className="w-56">
              <Switch
                size="sm"
                checked={showInactive}
                onChange={setShowInactive}
                label="Show removed"
              />
            </div>
          }
        />
        {loading ? (
          <LoadingBlock label={`Loading ${content.label.toLowerCase()}…`} />
        ) : error ? (
          <CardBody>
            <Alert tone="danger" title="Could not load">
              {error}
            </Alert>
          </CardBody>
        ) : offerings.length === 0 ? (
          <EmptyState
            title={`No ${content.label.toLowerCase()} yet`}
            description={
              canEdit
                ? `Add the first ${content.singular} and the bot can start answering questions about it.`
                : 'Nothing has been added for this tenant yet.'
            }
            icon={<Layers className="h-6 w-6" />}
          />
        ) : (
          <CardBody className="space-y-5">
            {groups.map(([category, items]) => (
              <div key={category}>
                <p className="mb-2 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                  {category}
                </p>
                <div className="divide-y divide-surface-line rounded-lg ring-1 ring-surface-line">
                  {items.map((item) => (
                    <div key={item.id} className="flex flex-wrap items-start gap-3 px-4 py-3">
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-sm font-medium text-slate-100">{item.name}</span>
                          {!item.is_active && <Badge tone="neutral">removed</Badge>}
                          {item.short_label && <Badge tone="accent">{item.short_label}</Badge>}
                          {item.price && <span className="text-xs text-slate-500">{item.price}</span>}
                        </div>
                        {item.short_description && (
                          <p className="mt-1 text-xs leading-relaxed text-slate-500">
                            {item.short_description}
                          </p>
                        )}
                        {Object.entries(item.attrs || {}).filter(([, v]) => v).length > 0 && (
                          <div className="mt-1.5 flex flex-wrap gap-1.5">
                            {Object.entries(item.attrs)
                              .filter(([, v]) => v)
                              .map(([k, v]) => (
                                <span
                                  key={k}
                                  className="rounded bg-surface-panel px-1.5 py-0.5 text-2xs text-slate-500 ring-1 ring-inset ring-surface-line"
                                >
                                  {k.replace(/_/g, ' ')}: {v}
                                </span>
                              ))}
                          </div>
                        )}
                      </div>
                      {(canEditRow || canRemove) && (
                        <div className="flex shrink-0 items-center gap-2">
                          {canEditRow && (
                            <Button
                              size="sm"
                              variant="secondary"
                              icon={<Pencil className="h-3.5 w-3.5" />}
                              onClick={() => setEditing(item)}
                            >
                              Edit
                            </Button>
                          )}
                          {canRemove && item.is_active &&
                            (confirmDelete === item.id ? (
                              <>
                                <Button
                                  size="sm"
                                  variant="danger"
                                  loading={action.busy}
                                  onClick={() => remove(item.id, true)}
                                >
                                  Delete forever
                                </Button>
                                <Button
                                  size="sm"
                                  variant="ghost"
                                  onClick={() => setConfirmDelete(null)}
                                >
                                  Cancel
                                </Button>
                              </>
                            ) : (
                              <Button
                                size="sm"
                                variant="ghost"
                                icon={<Trash2 className="h-3.5 w-3.5" />}
                                onClick={() => setConfirmDelete(item.id)}
                              >
                                Remove
                              </Button>
                            ))}
                          {canEditRow && !item.is_active && (
                            <Button
                              size="sm"
                              variant="ghost"
                              loading={action.busy}
                              onClick={() => action.run(() => offeringsApi.update(tenantId, item.id, { is_active: true })).then((r) => r && reload())}
                            >
                              Restore
                            </Button>
                          )}
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </CardBody>
        )}
      </Card>
    </div>
  )
}

type FormShape = {
  name: string
  category: string
  short_label: string
  short_description: string
  description: string
  price: string
  detail_url: string
  attrs: Record<string, string>
  is_active: boolean
}

function toShape(item?: Offering, defaults: string[] = []): FormShape {
  return {
    name: item?.name ?? '',
    category: item?.category || defaults[0] || 'general',
    short_label: item?.short_label ?? '',
    short_description: item?.short_description ?? '',
    description: item?.description ?? '',
    price: item?.price ?? '',
    detail_url: item?.detail_url ?? '',
    attrs: { ...(item?.attrs ?? {}) },
    is_active: item?.is_active ?? true,
  }
}

function OfferingForm({
  content,
  initial,
  busy,
  onSubmit,
  onCancel,
}: {
  content: ReturnType<typeof getVertical>['content']
  initial?: Offering
  busy: boolean
  onSubmit: (body: OfferingInput) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<FormShape>(() => toShape(initial, content.categories))
  const [touched, setTouched] = useState(false)

  const set = <K extends keyof FormShape>(key: K, value: FormShape[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const nameMissing = touched && !form.name.trim()

  const submit = () => {
    setTouched(true)
    if (!form.name.trim()) return
    const attrs: Record<string, string> = {}
    for (const [k, v] of Object.entries(form.attrs)) if (v.trim()) attrs[k] = v.trim()
    onSubmit({
      name: form.name.trim(),
      category: form.category.trim() || 'general',
      short_label: form.short_label.trim(),
      short_description: form.short_description.trim(),
      description: form.description.trim(),
      price: form.price.trim() || null,
      detail_url: form.detail_url.trim(),
      media_url: '',
      media_type: 'image',
      attrs,
      sort_order: initial?.sort_order ?? 0,
      is_active: form.is_active,
    })
  }

  return (
    <Card className="mt-4">
      <CardHeader
        title={initial ? `Edit ${initial.name}` : `Add a ${content.singular}`}
        description={
          content.extraFields.length
            ? `Everything except ${content.extraFields.map((f) => f.label.toLowerCase()).join(', ')} is shared with the bot's answers.`
            : undefined
        }
        actions={
          <Button size="sm" variant="ghost" icon={<X className="h-3.5 w-3.5" />} onClick={onCancel}>
            Close
          </Button>
        }
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label={`${content.label} name`}
            value={form.name}
            error={nameMissing ? 'A name is required' : undefined}
            onChange={(e) => set('name', e.target.value)}
            placeholder={content.singular === 'service' ? 'Web development' : 'Name'}
          />
          <Input
            label="Group"
            value={form.category}
            onChange={(e) => set('category', e.target.value)}
            hint="Free text. These become the groups in the list above."
            list="offering-groups"
          />
          <datalist id="offering-groups">
            {content.categories.map((c) => (
              <option key={c} value={c} />
            ))}
          </datalist>
        </div>

        {content.categories.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {content.categories.map((c) => (
              <button
                key={c}
                type="button"
                onClick={() => set('category', c)}
                className={cn(
                  'rounded-md px-2 py-1 text-xs ring-1 ring-inset transition',
                  form.category === c
                    ? 'bg-accent-500/15 font-medium text-accent-800 ring-accent-200'
                    : 'text-slate-400 ring-surface-line hover:bg-accent-50 hover:text-slate-100',
                )}
              >
                {c}
              </button>
            ))}
          </div>
        )}

        <Input
          label="Short description"
          value={form.short_description}
          onChange={(e) => set('short_description', e.target.value)}
          hint="One line. This is what the bot replies with in a chat."
        />

        <Textarea
          label="Full description"
          rows={4}
          value={form.description}
          onChange={(e) => set('description', e.target.value)}
          hint="The detail the bot reads out when a customer asks for more."
        />

        <div className="grid gap-4 sm:grid-cols-2">
          {content.priceLabel && (
            <Input
              label={content.priceLabel}
              value={form.price}
              onChange={(e) => set('price', e.target.value)}
              hint="Optional — leave blank if it is not a fixed price."
              prefix="₹"
            />
          )}
          <Input
            label="Short label"
            value={form.short_label}
            onChange={(e) => set('short_label', e.target.value)}
            hint="Shown as a small tag, e.g. “Popular”."
          />
          <Input
            label="Link"
            value={form.detail_url}
            onChange={(e) => set('detail_url', e.target.value)}
            placeholder="https://…"
          />
        </div>

        {content.extraFields.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-3">
            {content.extraFields.map((field) => (
              <Input
                key={field.key}
                label={field.label}
                value={form.attrs[field.key] ?? ''}
                onChange={(e) => set('attrs', { ...form.attrs, [field.key]: e.target.value })}
                placeholder={field.placeholder}
              />
            ))}
          </div>
        )}

        <Switch
          checked={form.is_active}
          onChange={(v) => set('is_active', v)}
          label="Visible to the bot"
          description="Turn off to keep the record but stop the bot offering it."
        />

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
