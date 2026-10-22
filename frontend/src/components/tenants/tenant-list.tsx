import { Building2, FlaskConical, PlusCircle, RefreshCw, ToggleLeft, ToggleRight, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { useTenants, tenantsApi } from '@/lib/tenants'
import { navigate } from '@/lib/router'
import { usePermissions } from '@/lib/permissions'
import { getVertical } from '@/lib/verticals'
import { useAction } from '@/lib/hooks'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { VerticalGlyph } from '@/components/vertical-icon'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import type { Tenant } from '@/lib/types'

export function TenantList() {
  const { tenants, loading, error, reload } = useTenants()
  const { canManageTenants } = usePermissions()
  const [confirming, setConfirming] = useState<string | null>(null)
  const [activeTestTenant, setActiveTestTenant] = useState<string | null>(null)
  const [switchingTenant, setSwitchingTenant] = useState<string | null>(null)
  const action = useAction()
  const toast = useToast()

  useEffect(() => {
    tenantsApi.getActiveTestTenant().then(setActiveTestTenant).catch(() => {})
  }, [])

  const handleToggleTestTenant = async (tenantId: string | null) => {
    setSwitchingTenant(tenantId ?? '__reset__')
    try {
      const res = await tenantsApi.setActiveTestTenant(tenantId)
      setActiveTestTenant(res.active_test_tenant)
      const activeObj = tenants.find((t) => t.id === res.active_test_tenant || t.slug === res.active_test_tenant)
      const name = activeObj?.display_name || res.active_test_tenant || 'Default routing'
      toast.push(
        tenantId
          ? `🟢 WhatsApp test bot switched to: ${name}. Incoming chats will now run this tenant.`
          : 'WhatsApp test override disabled. Normal routing restored.',
      )
    } catch (err: any) {
      toast.push(`Failed to set test tenant: ${err.message}`)
    } finally {
      setSwitchingTenant(null)
    }
  }

  const remove = async (tenant: Tenant) => {
    const result = await action.run(() => tenantsApi.remove(tenant.id))
    if (result) {
      toast.push(`Tenant "${tenant.id}" deleted`)
      setConfirming(null)
      reload()
    }
  }

  return (
    <div>
      <PageHeader
        title="Tenants"
        description="Each tenant is one business on WhatsApp. Behaviour comes from its profile — menus, intents, and features are all data."
        actions={
          <>
            <Button size="sm" variant="ghost" onClick={reload} icon={<RefreshCw className="h-4 w-4" />}>
              Refresh
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => navigate('/register')}
              icon={<PlusCircle className="h-4 w-4" />}
            >
              Register a tenant
            </Button>
          </>
        }
      />

      {/* Single-Number WhatsApp Testing Mode Banner */}
      <Card className="mb-6 p-5 border-emerald-500/30 bg-emerald-950/20">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-500/10 text-emerald-400 ring-1 ring-inset ring-emerald-500/20">
              <FlaskConical className="h-5 w-5" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-slate-100">Single-Number WhatsApp Testing Mode</h3>
                {activeTestTenant ? (
                  <Badge tone="success" className="bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40">
                    🟢 Active: {activeTestTenant}
                  </Badge>
                ) : (
                  <Badge tone="neutral">Default Tenant Routing</Badge>
                )}
              </div>
              <p className="mt-1 text-xs text-slate-400">
                You have 1 WhatsApp phone number. Toggle any tenant below to route your incoming messages to that tenant for testing.
                You can also test in WhatsApp directly by sending <code className="rounded bg-slate-800 px-1 py-0.5 text-emerald-300 font-mono">#tenants</code> or <code className="rounded bg-slate-800 px-1 py-0.5 text-emerald-300 font-mono">#tenant &lt;name&gt;</code>.
              </p>
            </div>
          </div>
          {activeTestTenant && (
            <Button
              size="sm"
              variant="ghost"
              disabled={switchingTenant !== null}
              onClick={() => handleToggleTestTenant(null)}
            >
              Reset to Default
            </Button>
          )}
        </div>
      </Card>

      {error && (
        <Alert tone="danger" title="Could not load tenants" className="mb-5">
          {error}
        </Alert>
      )}
      {action.error && (
        <Alert tone="danger" className="mb-5">
          {action.error}
        </Alert>
      )}

      {loading ? (
        <LoadingBlock label="Loading tenants…" />
      ) : tenants.length === 0 ? (
        <Card>
          <EmptyState
            icon={<Building2 className="h-8 w-8" />}
            title="No tenants registered yet"
            description="Registration asks for the company, the business field, its capabilities and its guardrails — then publishes a versioned profile the bot reads."
            action={
              canManageTenants ? (
                <Button variant="primary" onClick={() => navigate('/register')} icon={<PlusCircle className="h-4 w-4" />}>
                  Register your first tenant
                </Button>
              ) : null
            }
          />
        </Card>
      ) : (
        <div className="grid gap-3">
          {tenants.map((tenant) => {
            const vertical = getVertical(tenant.vertical)
            const open = () => navigate(`/tenants/${encodeURIComponent(tenant.id)}/overview`)
            const isTestActive = Boolean(
              (activeTestTenant && tenant.id && String(activeTestTenant) === String(tenant.id)) ||
              (activeTestTenant && tenant.slug && String(activeTestTenant).toLowerCase() === tenant.slug.toLowerCase())
            )
            const tenantKey = tenant.slug || String(tenant.id)
            return (
              <Card
                key={tenant.id}
                className={`p-5 transition hover:ring-accent-300 ${
                  isTestActive ? 'ring-2 ring-emerald-500/50 bg-emerald-950/10' : ''
                }`}
              >
                <div className="flex flex-wrap items-start gap-4">
                  <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-accent-50 text-accent-700 ring-1 ring-inset ring-accent-200">
                    <VerticalGlyph name={vertical.icon} className="h-5 w-5" />
                  </div>

                  <button type="button" onClick={open} className="min-w-0 flex-1 text-left">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold text-slate-100">{tenant.display_name || tenant.id}</span>
                      <Badge tone="accent">{vertical.short}</Badge>
                      {tenant.current_version ? (
                        <Badge tone="success">live v{tenant.current_version}</Badge>
                      ) : (
                        <Badge tone="warning">no published version</Badge>
                      )}
                      {tenant.status && tenant.status !== 'active' && (
                        <Badge tone="danger">{tenant.status}</Badge>
                      )}
                      {isTestActive && (
                        <Badge tone="success" className="bg-emerald-500/20 text-emerald-300 ring-1 ring-emerald-500/40">
                          🟢 Active Test Bot
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1.5 font-mono text-xs text-slate-500">
                      {tenant.id}
                      {tenant.waba_phone_id ? ` · phone ${tenant.waba_phone_id}` : ' · no phone bound'}
                    </p>
                    <p className="mt-2 max-w-2xl text-xs leading-relaxed text-slate-400">{vertical.blurb}</p>
                  </button>

                  <div className="flex shrink-0 items-center gap-2">
                    <Button
                      size="sm"
                      variant={isTestActive ? 'primary' : 'secondary'}
                      loading={Boolean(switchingTenant === tenantKey || (switchingTenant === '__reset__' && isTestActive))}
                      onClick={() => handleToggleTestTenant(isTestActive ? null : tenantKey)}
                      className={isTestActive ? 'bg-emerald-600 hover:bg-emerald-500 text-white' : ''}
                      icon={isTestActive ? <ToggleRight className="h-4 w-4" /> : <ToggleLeft className="h-4 w-4" />}
                      title={isTestActive ? 'Click to disable override and reset to default' : 'Activate this tenant on your single WhatsApp number'}
                    >
                      {isTestActive ? 'Active Test Bot' : 'Activate on WhatsApp'}
                    </Button>
                    <Button size="sm" variant="secondary" onClick={open}>
                      {canManageTenants ? 'Configure' : 'View'}
                    </Button>
                    {canManageTenants &&
                      (confirming === tenant.id ? (
                        <>
                          <Button size="sm" variant="danger" loading={action.busy} onClick={() => remove(tenant)}>
                            Confirm
                          </Button>
                          <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                            Cancel
                          </Button>
                        </>
                      ) : (
                        <Button
                          size="sm"
                          variant="ghost"
                          title="Delete tenant"
                          onClick={() => setConfirming(tenant.id)}
                          icon={<Trash2 className="h-4 w-4" />}
                        />
                      ))}
                  </div>
                </div>
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}
