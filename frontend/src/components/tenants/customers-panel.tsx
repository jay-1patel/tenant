import { useState } from 'react'
import { useAsync } from '@/lib/hooks'
import { money, operationsApi } from '@/lib/operations'
import { relativeTime } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

/**
 * Everyone the bot has sold to, taken a ticket from or chatted with,
 * aggregated by WhatsApp ID. Read-only; seeing it needs `view_customers`.
 */
export function CustomersPanel({ tenantId }: { tenantId: string }) {
  const [search, setSearch] = useState('')

  const state = useAsync(
    (signal) => operationsApi.tenantCustomers(tenantId, { q: search || undefined }, signal),
    [tenantId, search],
  )

  const customers = state.data?.customers ?? []

  return (
    <div>
      <PageHeader
        title="Customers"
        description="Customer details aggregated across orders, complaints and chat history, keyed by WhatsApp number."
        meta={
          state.data && (
            <>
              <Badge tone="muted">{state.data.count} shown</Badge>
              <Badge tone="accent">{customers.filter((c) => c.open_complaints > 0).length} with open complaints</Badge>
            </>
          )
        }
      />

      <div className="mb-4 max-w-sm">
        <Input
          label="Search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Name, mobile or WhatsApp ID"
        />
      </div>

      {state.loading && <LoadingBlock label="Reading customers…" />}
      {state.error && (
        <Alert tone="danger" title="Could not read customers">
          {state.error}
        </Alert>
      )}

      {state.data && customers.length === 0 && (
        <Card>
          <EmptyState
            title="No customers yet"
            description="Customers appear here once the bot has an order, complaint or conversation with them."
          />
        </Card>
      )}

      {customers.length > 0 && (
        <Card>
          <CardBody className="divide-y divide-surface-line">
            {customers.map((customer) => (
              <div key={customer.wa_id} className="flex flex-wrap items-center gap-3 py-3 first:pt-0 last:pb-0">
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">{customer.name || customer.wa_id}</p>
                  <p className="mt-0.5 truncate text-xs text-slate-500">
                    {customer.wa_id}
                    {customer.mobile && customer.mobile !== customer.wa_id ? ` · ${customer.mobile}` : ''}
                    {customer.last_active ? ` · last seen ${relativeTime(customer.last_active)}` : ''}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="accent">{customer.total_orders} orders</Badge>
                  {customer.total_complaints > 0 && (
                    <Badge tone={customer.open_complaints > 0 ? 'danger' : 'muted'}>
                      {customer.total_complaints} complaints
                    </Badge>
                  )}
                  <Badge tone="success">{money(customer.total_spent)} spent</Badge>
                </div>
              </div>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}
