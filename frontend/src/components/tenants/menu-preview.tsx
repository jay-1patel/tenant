import { EyeOff } from 'lucide-react'
import { useResolved } from './hooks'
import { navigate } from '@/lib/router'
import { usePermissions } from '@/lib/permissions'
import { FEATURE_LABELS, getVertical } from '@/lib/verticals'
import type { FeatureFlag } from '@/lib/types'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

export function MenuPreview({ tenantId }: { tenantId: string }) {
  const { data, error, loading } = useResolved(tenantId)
  const { canManageTenants } = usePermissions()

  if (loading) return <LoadingBlock label="Loading the menu…" />
  if (error || !data) {
    return (
      <Alert tone="danger" title="Could not load the menu">
        {error ?? 'Unknown error'}
      </Alert>
    )
  }

  const menu = data.menu
  const buttons = [...(menu?.buttons ?? [])].sort((a, b) => a.sort_order - b.sort_order)
  const sections = Array.from(new Set(buttons.map((b) => b.section || 'General')))

  return (
    <div>
      <PageHeader
        title="Menu"
        description="The WhatsApp list menu, rendered from the profile. A button is hidden when the feature it depends on is off — that is the same rule the runtime uses."
        actions={
          canManageTenants ? (
            <Button size="sm" variant="secondary" onClick={() => navigate(`/tenants/${tenantId}/menu-edit`)}>
              Edit menu options
            </Button>
          ) : null
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="As the customer sees it" />
          <CardBody>
            <div className="rounded-xl bg-surface p-4 text-slate-200 ring-1 ring-surface-line">
              {menu?.header && <p className="text-sm font-semibold text-slate-100">{menu.header}</p>}
              <p className="mt-1 text-xs leading-relaxed text-slate-500">{menu?.body}</p>
              <div className="mt-3 rounded-lg border border-accent-200 bg-accent-50 px-3 py-2 text-center text-xs font-medium text-accent-700">
                {menu?.button_text || 'Show Options'}
              </div>
              {menu?.footer && <p className="mt-3 text-xs text-slate-500">{menu.footer}</p>}
            </div>
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {sections.map((section) => (
            <Card key={section}>
              <CardHeader title={section} description={`${buttons.filter((b) => (b.section || 'General') === section).length} button(s)`} />
              <CardBody className="space-y-2">
                {buttons
                  .filter((b) => (b.section || 'General') === section)
                  .map((button) => {
                    const gated = button.requires_feature ? !data.features[button.requires_feature as FeatureFlag] : false
                    const hidden = !button.enabled || gated
                    return (
                      <div
                        key={button.id}
                        className={`rounded-lg p-3 ring-1 ring-inset ${
                          hidden ? 'bg-surface-panel ring-surface-line/60 opacity-70' : 'bg-surface-panel ring-surface-line'
                        }`}
                      >
                        <div className="flex flex-wrap items-center gap-2">
                          {button.icon && <span className="text-sm">{button.icon}</span>}
                          <span className="text-xs font-medium text-slate-100">{button.title}</span>
                          <code className="rounded bg-surface-panel px-1.5 py-0.5 font-mono text-2xs text-slate-500">
                            {button.id}
                          </code>
                          {button.flow && <Badge tone="accent">flow: {button.flow}</Badge>}
                          {button.intent && <Badge tone="neutral">intent: {button.intent}</Badge>}
                          {button.out_of_hours_only && <Badge tone="warning">out of hours only</Badge>}
                          {!button.enabled && <Badge tone="muted">disabled</Badge>}
                          {gated && (
                            <Badge tone="danger">
                              <EyeOff className="h-3 w-3" />
                              needs {FEATURE_LABELS[button.requires_feature as FeatureFlag]?.label}
                            </Badge>
                          )}
                        </div>
                        {button.description && (
                          <p className="mt-1 text-xs leading-relaxed text-slate-500">{button.description}</p>
                        )}
                      </div>
                    )
                  })}
              </CardBody>
            </Card>
          ))}

          {!buttons.length && (
            <Card>
              <CardBody>
                <p className="text-xs text-slate-500">
                  This profile has no menu buttons. The {getVertical(data.vertical).short} defaults usually supply
                  them — publish a version to inherit them.
                </p>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}
