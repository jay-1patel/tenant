import { useState } from 'react'
import { useAsync } from '@/lib/hooks'
import { ORDER_STATUSES, money, operationsApi } from '@/lib/operations'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

const STATUS_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  placed: 'neutral',
  confirmed: 'accent',
  processing: 'accent',
  shipped: 'warning',
  delivered: 'success',
  completed: 'success',
  cancelled: 'danger',
  returned: 'danger',
}

const PAYMENT_TONE: Record<string, 'neutral' | 'accent' | 'success' | 'warning' | 'danger' | 'muted'> = {
  pending: 'warning',
  paid: 'success',
  failed: 'danger',
  refunded: 'muted',
  cod: 'neutral',
}

/**
 * Orders placed through the B2B and B2C bot flows. Read-only; seeing it needs
 * `view_orders` — status changes stay on the backend order endpoints.
 */
export function OrdersPanel({ tenantId }: { tenantId: string }) {
  const [status, setStatus] = useState('all')
  const [search, setSearch] = useState('')

  const state = useAsync(
    (signal) =>
      operationsApi.tenantOrders(tenantId, { status: status === 'all' ? undefined : status, q: search || undefined }, signal),
    [tenantId, status, search],
  )

  const orders = state.data?.orders ?? []
  const counts = state.data?.counts

  return (
    <div>
      <PageHeader
        title="Orders"
        description="Every order the bot has taken, newest first. Filter by status or search by order number, customer or phone."
        meta={
          counts && (
            <>
              <Badge tone="muted">{counts.total} total</Badge>
              <Badge tone="warning">{counts.placed} placed</Badge>
              <Badge tone="success">{counts.delivered} delivered</Badge>
              <Badge tone="accent">{money(counts.revenue)} revenue</Badge>
            </>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-end gap-4">
        <div className="w-44">
          <Select label="Status" value={status} onChange={(e) => setStatus(e.target.value)}>
            {['all', ...ORDER_STATUSES].map((filter) => (
              <option key={filter} value={filter}>
                {filter === 'all' ? 'All statuses' : filter.replace('_', ' ')}
              </option>
            ))}
          </Select>
        </div>
        <div className="min-w-0 max-w-sm flex-1">
          <Input
            label="Search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Order number, customer or phone"
          />
        </div>
      </div>

      {state.loading && <LoadingBlock label="Reading orders…" />}
      {state.error && (
        <Alert tone="danger" title="Could not read orders">
          {state.error}
        </Alert>
      )}

      {state.data && orders.length === 0 && (
        <Card>
          <EmptyState
            title="No orders"
            description="No orders match this filter. Orders appear here as soon as a customer completes one through the bot."
          />
        </Card>
      )}

      {orders.length > 0 && (
        <Card>
          <CardBody className="divide-y divide-surface-line">
            {orders.map((order) => (
              <div key={order.id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">
                    {order.order_number || `Order #${order.id}`}
                    <span className="ml-2 text-xs font-normal text-slate-500">
                      {order.items?.length ?? 0} item{(order.items?.length ?? 0) === 1 ? '' : 's'}
                    </span>
                  </p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {order.customer_name || order.wa_id || 'Unknown customer'}
                    {order.customer_mobile ? ` · ${order.customer_mobile}` : ''}
                    {order.order_type ? ` · ${order.order_type}` : ''}
                    {order.created_at ? ` · ${formatDate(order.created_at)}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  {order.status && (
                    <Badge tone={STATUS_TONE[order.status] ?? 'neutral'}>{order.status.replace('_', ' ')}</Badge>
                  )}
                  {order.payment_status && (
                    <Badge tone={PAYMENT_TONE[order.payment_status] ?? 'muted'}>{order.payment_status}</Badge>
                  )}
                  <Badge tone="success">{money(order.total_amount)}</Badge>
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}
