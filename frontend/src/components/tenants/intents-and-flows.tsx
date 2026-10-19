import { GitBranch } from 'lucide-react'
import { useResolved } from './hooks'
import { FEATURE_LABELS } from '@/lib/verticals'
import type { FeatureFlag, IntentSpec } from '@/lib/types'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'

export function IntentsAndFlows({ tenantId }: { tenantId: string }) {
  const { data, error, loading } = useResolved(tenantId)

  if (loading) return <LoadingBlock label="Loading intents…" />
  if (error || !data) {
    return (
      <Alert tone="danger" title="Could not load intents">
        {error ?? 'Unknown error'}
      </Alert>
    )
  }

  const active = data.active_intents ?? []
  const inactive = data.inactive_intents ?? []
  return (
    <div>
      <PageHeader
        title="Intents"
        description="An intent only wins when its feature flag is on — that is the gate that makes 'place order' unreachable for a tenant that does not sell online."
        meta={
          <>
            <Badge tone="success">{active.length} active intents</Badge>
            <Badge tone="muted">{inactive.length} gated off</Badge>
          </>
        }
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Active intents" description="What the classifier can route to right now." icon={<GitBranch className="h-4 w-4" />} />
          <CardBody className="space-y-2">
            {active.map((intent) => (
              <IntentRow key={intent.name} intent={intent} />
            ))}
            {!active.length && <p className="text-xs text-slate-500">No active intents in this profile.</p>}
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Gated off" description="Defined, but unreachable while their feature flag is off." />
          <CardBody className="space-y-2">
            {inactive.map((intent) => (
              <IntentRow key={intent.name} intent={intent} muted />
            ))}
            {!inactive.length && <p className="text-xs text-slate-500">Nothing is gated off.</p>}
          </CardBody>
        </Card>
      </div>


    </div>
  )
}

function IntentRow({ intent, muted }: { intent: IntentSpec; muted?: boolean }) {
  return (
    <div className={`rounded-lg p-3 ring-1 ring-inset ${muted ? 'bg-surface-panel ring-surface-line/60' : 'bg-surface-panel ring-surface-line'}`}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-slate-100">{intent.name}</span>
        {intent.flow && <Badge tone="accent">→ {intent.flow}</Badge>}
        {intent.requires_feature && (
          <Badge tone={muted ? 'danger' : 'neutral'}>
            requires {FEATURE_LABELS[intent.requires_feature as FeatureFlag]?.label ?? intent.requires_feature}
          </Badge>
        )}
        {!intent.enabled && <Badge tone="muted">disabled</Badge>}
      </div>
      {intent.keywords?.length ? (
        <p className="mt-1.5 text-xs leading-relaxed text-slate-500">
          {intent.keywords.slice(0, 14).join(' · ')}
        </p>
      ) : null}
      {intent.examples?.length ? (
        <p className="mt-1 text-xs italic leading-relaxed text-slate-600">“{intent.examples[0]}”</p>
      ) : null}
    </div>
  )
}


