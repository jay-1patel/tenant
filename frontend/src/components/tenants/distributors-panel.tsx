import { useState } from 'react'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import {
  DISTRIBUTOR_TIERS,
  type Distributor,
  type DistributorInput,
  money,
  operationsApi,
} from '@/lib/operations'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

const TIER_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  Bronze: 'muted',
  Silver: 'neutral',
  Gold: 'warning',
  Platinum: 'accent',
}

interface DistributorFormShape {
  wa_id: string
  name: string
  phone: string
  email: string
  region: string
  tier: string
  product_interests: string
  sales_volume: string
  outstanding_payments: string
  notes: string
}

function toShape(distributor?: Distributor | null): DistributorFormShape {
  return {
    wa_id: distributor?.wa_id ?? '',
    name: distributor?.name ?? '',
    phone: distributor?.phone ?? '',
    email: distributor?.email ?? '',
    region: distributor?.region ?? '',
    tier: distributor?.tier ?? 'Bronze',
    product_interests: (distributor?.product_interests ?? []).join(', '),
    sales_volume: distributor ? String(distributor.sales_volume ?? '') : '',
    outstanding_payments: distributor ? String(distributor.outstanding_payments ?? '') : '',
    notes: distributor?.notes ?? '',
  }
}

/**
 * B2B distributor directory: tier, region, volumes and outstanding payments.
 * Reading needs `view_distributors`; adding, editing and deleting needs
 * `manage_distributors`.
 */
export function DistributorsPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()
  const canManage = can('manage_distributors')

  const [tier, setTier] = useState('all')
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<Distributor | null>(null)
  const [creating, setCreating] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const state = useAsync(
    (signal) =>
      operationsApi.distributors(
        tenantId,
        { q: search || undefined, tier: tier === 'all' ? undefined : tier },
        signal,
      ),
    [tenantId, tier, search],
  )

  const distributors = state.data?.distributors ?? []

  const submit = async (input: DistributorInput & { wa_id?: string }) => {
    if (editing) {
      const { wa_id, ...rest } = input
      const result = await action.run(() => operationsApi.updateDistributor(tenantId, editing.wa_id, rest))
      if (result) {
        toast.push('Distributor updated')
        setEditing(null)
        state.reload()
      }
      return
    }
    if (!input.wa_id?.trim()) return
    const { wa_id, ...rest } = input
    const result = await action.run(() =>
      operationsApi.createDistributor(tenantId, { ...rest, wa_id: wa_id.trim() }),
    )
    if (result) {
      toast.push('Distributor added')
      setCreating(false)
      state.reload()
    }
  }

  const remove = async (distributor: Distributor) => {
    const result = await action.run(() => operationsApi.deleteDistributor(tenantId, distributor.wa_id))
    if (result) {
      toast.push('Distributor deleted')
      setConfirmDelete(null)
      if (editing?.wa_id === distributor.wa_id) setEditing(null)
      state.reload()
    }
  }

  return (
    <div>
      <PageHeader
        title="Distributors"
        description="Authorized resellers with their tier, region, sales volume and outstanding payments."
        actions={
          canManage && !creating && !editing && (
            <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
              Add distributor
            </Button>
          )
        }
        meta={state.data && <Badge tone="muted">{distributors.length} shown</Badge>}
      />

      <div className="mb-4 flex flex-wrap items-center gap-1.5">
        {['all', ...DISTRIBUTOR_TIERS].map((filter) => (
          <button
            key={filter}
            type="button"
            onClick={() => setTier(filter)}
            className={cn(
              'rounded-lg px-3 py-1.5 text-xs font-medium capitalize transition',
              tier === filter
                ? 'bg-accent-100 text-accent-800 ring-1 ring-inset ring-accent-300'
                : 'text-slate-400 hover:bg-surface-panel hover:text-slate-200',
            )}
          >
            {filter}
          </button>
        ))}
      </div>

      {!creating && !editing && (
        <div className="mb-4 max-w-sm">
          <Input
            label="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Name, phone, email or WhatsApp ID"
          />
        </div>
      )}

      {(creating || editing) && (
        <DistributorForm
          initial={editing}
          busy={action.busy}
          error={action.error}
          onCancel={() => {
            setCreating(false)
            setEditing(null)
          }}
          onSubmit={submit}
        />
      )}

      {state.loading && <LoadingBlock label="Reading distributors…" />}
      {state.error && (
        <Alert tone="danger" title="Could not read distributors">
          {state.error}
        </Alert>
      )}

      {state.data && distributors.length === 0 && !creating && !editing && (
        <Card>
          <EmptyState
            title="No distributors"
            description="No distributors match this filter. Add one by hand, or let the bot's B2B flow register them."
            action={
              canManage && (
                <Button variant="subtle" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                  Add distributor
                </Button>
              )
            }
          />
        </Card>
      )}

      {distributors.length > 0 && (
        <Card>
          <CardBody className="divide-y divide-surface-line">
            {distributors.map((distributor) => (
              <div key={distributor.wa_id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {distributor.name || distributor.wa_id}
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {distributor.wa_id}
                    {distributor.region ? ` · ${distributor.region}` : ''}
                    {distributor.phone && distributor.phone !== distributor.wa_id ? ` · ${distributor.phone}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone={TIER_TONE[distributor.tier] ?? 'neutral'}>{distributor.tier}</Badge>
                  {distributor.sales_volume > 0 && (
                    <Badge tone="success">{money(distributor.sales_volume)} volume</Badge>
                  )}
                  {distributor.outstanding_payments > 0 && (
                    <Badge tone="danger">{money(distributor.outstanding_payments)} outstanding</Badge>
                  )}
                  {canManage && (
                    <>
                      <Button size="sm" variant="ghost" onClick={() => setEditing(distributor)}>
                        <Pencil className="h-3.5 w-3.5" /> Edit
                      </Button>
                      {confirmDelete === distributor.wa_id ? (
                        <>
                          <Button
                            size="sm"
                            variant="danger"
                            loading={action.busy}
                            onClick={() => remove(distributor)}
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
                          className="text-rose-400 hover:text-rose-300"
                          onClick={() => setConfirmDelete(distributor.wa_id)}
                        >
                          <Trash2 className="h-3.5 w-3.5" /> Delete
                        </Button>
                      )}
                    </>
                  )}
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function DistributorForm({
  initial,
  busy,
  error,
  onSubmit,
  onCancel,
}: {
  initial: Distributor | null
  busy: boolean
  error: string | null
  onSubmit: (input: DistributorInput & { wa_id?: string }) => void
  onCancel: () => void
}) {
  const [form, setForm] = useState<DistributorFormShape>(() => toShape(initial))
  const [touched, setTouched] = useState(false)

  const set = <K extends keyof DistributorFormShape>(key: K, value: DistributorFormShape[K]) =>
    setForm((f) => ({ ...f, [key]: value }))

  const waIdMissing = touched && !initial && !form.wa_id.trim()
  const nameMissing = touched && !form.name.trim()
  const phoneMissing = touched && !form.phone.trim()
  const regionMissing = touched && !form.region.trim()

  const phoneValid = !form.phone.trim() || /^\+?\d{10,15}$/.test(form.phone.trim().replace(/\s+/g, ''))

  const submit = () => {
    setTouched(true)
    if (!initial && !form.wa_id.trim()) return
    if (!form.name.trim()) return
    if (!form.phone.trim()) return
    if (!form.region.trim()) return
    if (!phoneValid) return
    onSubmit({
      wa_id: form.wa_id.trim(),
      name: form.name.trim(),
      phone: form.phone.trim(),
      email: form.email.trim(),
      region: form.region.trim(),
      tier: form.tier,
      product_interests: form.product_interests
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      sales_volume: Number(form.sales_volume) || 0,
      outstanding_payments: Number(form.outstanding_payments) || 0,
      notes: form.notes.trim(),
    })
  }

  return (
    <Card className="mb-4">
      <CardHeader
        title={initial ? `Edit ${initial.name || initial.wa_id}` : 'Add a distributor'}
        description="The B2B bot prices and prioritizes from the tier; product interests feed the campaign audience filters."
      />
      <CardBody className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="WhatsApp ID"
            value={form.wa_id}
            error={waIdMissing ? 'A WhatsApp ID is required' : undefined}
            onChange={(e) => set('wa_id', e.target.value)}
            placeholder="919876543210"
            disabled={Boolean(initial)}
            hint={initial ? 'The ID a distributor is keyed by — it cannot change.' : undefined}
          />
          <Input label="Name" value={form.name} error={nameMissing ? 'Name is required' : undefined} onChange={(e) => set('name', e.target.value)} />
          <Input label="Phone" value={form.phone} error={phoneMissing ? 'Phone number is required' : (!phoneValid ? 'Phone must be 10-15 digits (with optional +)' : undefined)} onChange={(e) => set('phone', e.target.value)} />
          <Input label="Email" value={form.email} onChange={(e) => set('email', e.target.value)} />
          <Input label="Region" value={form.region} error={regionMissing ? 'Region is required' : undefined} onChange={(e) => set('region', e.target.value)} />
          <Select label="Tier" value={form.tier} onChange={(e) => set('tier', e.target.value)}>
            {DISTRIBUTOR_TIERS.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </Select>
        </div>

        <Input
          label="Product interests"
          value={form.product_interests}
          onChange={(e) => set('product_interests', e.target.value)}
          hint="Comma separated. Campaign audience filters match against these."
          placeholder="chikki, snacks"
        />

        <div className="grid gap-4 sm:grid-cols-2">
          <Input
            label="Sales volume"
            value={form.sales_volume}
            onChange={(e) => set('sales_volume', e.target.value)}
            prefix="₹"
            hint="Lifetime sales value — blank counts as 0."
          />
          <Input
            label="Outstanding payments"
            value={form.outstanding_payments}
            onChange={(e) => set('outstanding_payments', e.target.value)}
            prefix="₹"
            hint="Unpaid balance the bot quotes when a distributor asks."
          />
        </div>

        <Textarea label="Notes" rows={3} value={form.notes} onChange={(e) => set('notes', e.target.value)} />

        {error && <Alert tone="danger" title="Could not save">{error}</Alert>}

        <div className="flex items-center gap-2">
          <Button variant="primary" loading={busy} onClick={submit}>
            {initial ? 'Save changes' : 'Add distributor'}
          </Button>
          <Button variant="ghost" onClick={onCancel}>
            Cancel
          </Button>
        </div>
      </CardBody>
    </Card>
  )
}
