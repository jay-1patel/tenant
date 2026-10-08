import { type ReactNode, useState } from 'react'
import { ArrowLeft, Blocks, ChevronDown, ClipboardCheck, LayoutGrid, LogOut, PlusCircle, ScrollText, Send, UserRound, Users, ShieldCheck, KeyRound } from 'lucide-react'
import { useAuth } from '@/lib/auth'
import { useTenantFeatures, useTenants } from '@/lib/tenants'
import { useOfferingsCount } from '@/lib/offerings'
import { buildTenantNav } from '@/lib/navigation'
import { navigate, type RouteMatch } from '@/lib/router'
import { TEAM_PERMISSION, TENANT_PERMISSION, usePermissions } from '@/lib/permissions'
import { getVertical } from '@/lib/verticals'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { VerticalGlyph } from '@/components/vertical-icon'

/**
 * The sidebar is built per tenant rather than hard-coded: `buildTenantNav`
 * weighs the tenant's vertical, its feature flags and the signed-in admin's
 * permissions. See `@/lib/navigation`.
 */
export function AppShell({ route, children }: { route: RouteMatch; children: ReactNode }) {
  const { identity, logout } = useAuth()
  const { can } = usePermissions()
  const { tenants, active, setActive } = useTenants()
  const [switcherOpen, setSwitcherOpen] = useState(false)

  const tenantScoped = Boolean(route.tenantId)
  const features = useTenantFeatures(route.tenantId)
  const nav = buildTenantNav({ vertical: active?.vertical, features, can })
  const contentCount = useOfferingsCount(
    route.tenantId && can('view_products') ? route.tenantId : null,
  )

  return (
    <div className="flex h-full">
      <aside className="flex w-64 shrink-0 flex-col border-r border-surface-line bg-white">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-accent-100 text-accent-800 ring-1 ring-inset ring-accent-300">
            <Blocks className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-100">Tenant Console</p>
            <p className="text-xs text-slate-500">Multi-tenant WhatsApp</p>
          </div>
        </div>

        <div className="px-3">
          {can(TENANT_PERMISSION) || identity?.role === 'admin' ? (
            <Button
              variant="primary"
              className="w-full"
              icon={<PlusCircle className="h-4 w-4" />}
              onClick={() => navigate('/register')}
            >
              Register a tenant
            </Button>
          ) : (
            <p className="rounded-lg bg-surface-raised px-3 py-2.5 text-xs leading-relaxed text-slate-500 ring-1 ring-surface-line">
              Read-only access. Ask a super admin for the manage_operations permission to register or edit
              tenants.
            </p>
          )}
        </div>

        {identity?.role === 'super_admin' && (
          <div className="relative mt-4 px-3">
            <button
              type="button"
              onClick={() => setSwitcherOpen((v) => !v)}
              className="flex w-full items-center gap-2.5 rounded-lg bg-surface px-3 py-2.5 text-left ring-1 ring-surface-line transition hover:bg-surface-panel"
            >
              <VerticalGlyph name={getVertical(active?.vertical).icon} className="h-4 w-4 shrink-0 text-accent-700" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-xs font-medium text-slate-100">
                  {active?.display_name || active?.id || 'No tenant'}
                </span>
                <span className="block truncate text-xs text-slate-500">
                  {active ? getVertical(active.vertical).short : 'select a tenant'}
                </span>
              </span>
              <ChevronDown className={cn('h-4 w-4 shrink-0 text-slate-500 transition', switcherOpen && 'rotate-180')} />
            </button>

            {switcherOpen && (
              <div className="absolute left-3 right-3 top-full z-30 mt-1 overflow-hidden rounded-lg bg-surface-overlay ring-1 ring-surface-line shadow-xl">
                <button
                  type="button"
                  onClick={() => {
                    setSwitcherOpen(false)
                    navigate('/tenants')
                  }}
                  className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-slate-300 hover:bg-surface-panel"
                >
                  <LayoutGrid className="h-3.5 w-3.5" />
                  All tenants
                  <span className="ml-auto text-slate-500">{tenants.length}</span>
                </button>
                <div className="max-h-72 overflow-y-auto scroll-thin">
                  {tenants.map((tenant) => (
                    <button
                      key={tenant.id}
                      type="button"
                      onClick={() => {
                        setActive(tenant.id)
                        setSwitcherOpen(false)
                        navigate(`/tenants/${encodeURIComponent(tenant.id)}/overview`)
                      }}
                      className={cn(
                        'flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-panel',
                        tenant.id === active?.id ? 'text-accent-700' : 'text-slate-300',
                      )}
                    >
                      <VerticalGlyph name={getVertical(tenant.vertical).icon} className="h-3.5 w-3.5 shrink-0" />
                      <span className="min-w-0 flex-1 truncate">{tenant.display_name || tenant.id}</span>
                      {tenant.current_version ? (
                        <span className="shrink-0 text-2xs text-slate-500">v{tenant.current_version}</span>
                      ) : null}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        <nav className="mt-4 flex-1 space-y-4 overflow-y-auto px-3 scroll-thin">
          {tenantScoped && route.tenantId ? (
            <div className="space-y-0.5">
              <p className="px-3 pb-1 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                {active?.display_name || active?.id || route.tenantId}
              </p>
              {nav.map((item) => {
                const Icon = item.icon
                const isActive = route.view === item.id
                return (
                  <button
                    key={item.id}
                    type="button"
                    onClick={() => navigate(`/tenants/${encodeURIComponent(route.tenantId!)}/${item.id}`)}
                    className={cn(
                      'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                      isActive
                        ? 'bg-accent-100 font-medium text-accent-800'
                        : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                    )}
                  >
                    <Icon
                      className={cn('h-4 w-4 shrink-0', item.showsCount && !isActive && 'text-accent-600')}
                    />
                    <span className="min-w-0 flex-1 truncate">{item.label}</span>
                    {item.showsCount && contentCount !== null && (
                      <span className="shrink-0 text-2xs text-slate-500">{contentCount}</span>
                    )}
                  </button>
                )
              })}
            </div>
          ) : identity?.role !== 'super_admin' && identity?.tenant_id ? (
            <div className="space-y-0.5">
              <p className="px-3 pb-1 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                Your tenant
              </p>
              <button
                type="button"
                onClick={() => navigate(`/tenants/${encodeURIComponent(identity.tenant_id!)}/overview`)}
                className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-slate-400 transition hover:bg-accent-50 hover:text-slate-100"
              >
                <ArrowLeft className="h-4 w-4 shrink-0" />
                <span className="min-w-0 flex-1 truncate">
                  {tenants.find((t) => t.id === identity.tenant_id)?.display_name || identity.tenant_id}
                </span>
              </button>
            </div>
          ) : (
            <p className="px-3 text-xs leading-relaxed text-slate-500">
              Select a tenant to configure its profile, or register a new one.
            </p>
          )}

          {(identity?.role === 'super_admin' || (identity && identity.role !== 'super_admin' && can('manage_operations'))) && (
            <div className="border-t border-surface-line pt-3">
              {identity?.role === 'super_admin' ? (
<<<<<<< HEAD
                <div>
=======
                <>
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
                  <button
                    type="button"
                    onClick={() => navigate('/tenant-requests')}
                    className={cn(
                      'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                      route.view === 'tenant-requests'
                        ? 'bg-accent-100 font-medium text-accent-800'
                        : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                    )}
                  >
                    <ClipboardCheck className="h-4 w-4 shrink-0" />
                    Tenant change review
                  </button>
<<<<<<< HEAD
                <button
                  type="button"
                  onClick={() => navigate('/api-requests')}
                  className={cn(
                    'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                    route.view === 'api-requests'
                      ? 'bg-accent-100 font-medium text-accent-800'
                      : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                  )}
                >
                  <ShieldCheck className="h-4 w-4 shrink-0" />
                  API access review
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/audit-history')}
                  className={cn(
                    'mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                    route.view === 'audit-history'
                      ? 'bg-accent-100 font-medium text-accent-800'
                      : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                  )}
                >
                  <ScrollText className="h-4 w-4 shrink-0" />
                  Audit history
                </button>
                </div>
              ) : (
                <>
                  {identity?.tenant_id && (
                    <button
                      type="button"
                      onClick={() => navigate(`/tenants/${encodeURIComponent(identity.tenant_id!)}/api-access`)}
                      className={cn(
                        'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                        route.view === 'api-access'
                          ? 'bg-accent-100 font-medium text-accent-800'
                          : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                      )}
                    >
                      <KeyRound className="h-4 w-4 shrink-0" />
                      API access
                    </button>
                  )}
=======
                  <button
                    type="button"
                    onClick={() => navigate('/api-requests')}
                    className={cn(
                      'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                      route.view === 'api-requests'
                        ? 'bg-accent-100 font-medium text-accent-800'
                        : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                    )}
                  >
                    <ShieldCheck className="h-4 w-4 shrink-0" />
                    API access review
                  </button>
                  <button
                    type="button"
                    onClick={() => navigate('/audit-history')}
                    className={cn(
                      'mt-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                      route.view === 'audit-history'
                        ? 'bg-accent-100 font-medium text-accent-800'
                        : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                    )}
                  >
                    <ScrollText className="h-4 w-4 shrink-0" />
                    Audit history
                  </button>
                </>
              ) : (
                <>
                  {identity?.tenant_id && (
                    <button
                      type="button"
                      onClick={() => navigate(`/tenants/${encodeURIComponent(identity.tenant_id!)}/api-access`)}
                      className={cn(
                        'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                        route.view === 'api-access'
                          ? 'bg-accent-100 font-medium text-accent-800'
                          : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                      )}
                    >
                      <KeyRound className="h-4 w-4 shrink-0" />
                      API access
                    </button>
                  )}
>>>>>>> ad059aece57ef10c6e324d3f82e86b193f7ce21e
                  <button
                    type="button"
                    onClick={() => navigate('/tenant-requests')}
                    className={cn(
                      'mb-1 flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                      route.view === 'tenant-requests'
                        ? 'bg-accent-100 font-medium text-accent-800'
                        : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                    )}
                  >
                    <Send className="h-4 w-4 shrink-0" />
                    My change requests
                  </button>
                </>
              )}
            </div>
          )}

          {can(TEAM_PERMISSION) && (
            <div className="border-t border-surface-line pt-3">
              <button
                type="button"
                onClick={() => navigate('/team')}
                className={cn(
                  'flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition',
                  route.view === 'team'
                    ? 'bg-accent-100 font-medium text-accent-800'
                    : 'text-slate-400 hover:bg-accent-50 hover:text-slate-100',
                )}
              >
                <Users className="h-4 w-4 shrink-0" />
                Team & permissions
              </button>
            </div>
          )}
        </nav>

        <div className="border-t border-surface-line p-3">
          <div className="flex items-center gap-2.5 rounded-lg px-2 py-2">
            <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-50 text-accent-700 ring-1 ring-inset ring-accent-200">
              <UserRound className="h-4 w-4" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm text-slate-200">{identity?.username}</p>
              <Badge tone={(identity?.role === 'super_admin' || identity?.role === 'admin') ? 'accent' : 'neutral'} className="mt-0.5">
                {identity?.role === 'super_admin' ? 'super admin' : identity?.role === 'admin' ? 'admin' : 'sub admin'}
              </Badge>
            </div>
            <button
              type="button"
              onClick={logout}
              title="Sign out"
              className="shrink-0 rounded-md p-1.5 text-slate-500 transition hover:bg-accent-50 hover:text-rose-700"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>

      <main className="min-w-0 flex-1 overflow-y-auto bg-surface scroll-thin">
        <div className="mx-auto max-w-6xl px-8 py-8">{children}</div>
      </main>
    </div>
  )
}
