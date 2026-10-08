import { useState } from 'react'
import { History, Rocket, Undo2 } from 'lucide-react'
import { useAction } from '@/lib/hooks'
import { tenantsApi } from '@/lib/tenants'
import { formatDate, isTruthyFlag, relativeTime } from '@/lib/format'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { useAuth } from '@/lib/auth'
import { useTenantDetail, useVersions } from './hooks'

export function VersionsPanel({ tenantId }: { tenantId: string }) {
  const versions = useVersions(tenantId)
  const detail = useTenantDetail(tenantId)
  const action = useAction()
  const toast = useToast()
  const { identity } = useAuth()
  const isSuperAdmin = identity?.role === 'super_admin'
  const [confirming, setConfirming] = useState<number | null>(null)
  const [preview, setPreview] = useState<{ version: number; data: Record<string, unknown> } | null>(null)

  const publish = async () => {
    const result = await action.run(() => tenantsApi.publish(tenantId))
    if (result) {
      if (result.status === 'pending_approval') {
        toast.push(result.message ?? 'Change sent for super admin approval.')
      } else {
        toast.push(`Published version ${result.version}`)
      }
      versions.reload()
      detail.reload()
    }
  }

  const rollback = async (version: number) => {
    const result = await action.run(() => tenantsApi.rollback(tenantId, version))
    if (result) {
      toast.push(`Rolled back to v${result.version}`)
      setConfirming(null)
      versions.reload()
      detail.reload()
    }
  }

  const openVersion = async (version: number) => {
    if (preview?.version === version) {
      setPreview(null)
      return
    }
    const record = await action.run(() => tenantsApi.version(tenantId, version))
    if (record) setPreview({ version, data: record })
  }

  const rows = versions.data?.versions ?? []
  const current = versions.data?.current_version ?? 0

  return (
    <div>
      <PageHeader
        title="Versions"
        description="Publishing appends an immutable version and swaps the live profile. Rolling back never deletes anything — it re-points which version is current."
        actions={
          <Button
            variant="primary"
            size="sm"
            loading={action.busy}
            icon={<Rocket className="h-4 w-4" />}
            onClick={publish}
          >
            {isSuperAdmin ? 'Publish draft' : 'Submit for approval'}
          </Button>
        }
        meta={
          <Badge tone={current ? 'success' : 'warning'}>
            {current ? `live version v${current}` : 'nothing published yet'}
          </Badge>
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      {versions.loading ? (
        <LoadingBlock label="Loading versions…" />
      ) : (
        <Card>
          <CardHeader title="History" description={`${rows.length} version(s)`} icon={<History className="h-4 w-4" />} />
          <CardBody>
            {!rows.length ? (
              <p className="text-xs text-slate-500">
                No versions yet. Save a draft in the profile editor, then publish it here.
              </p>
            ) : (
              <div className="divide-y divide-surface-line">
                {rows.map((row) => {
                  const isCurrent = isTruthyFlag(row.is_current) || row.version === current
                  return (
                    <div key={row.version} className="flex flex-wrap items-center gap-3 py-3">
                      <div className="w-14 shrink-0">
                        <span className="font-mono text-sm text-slate-100">v{row.version}</span>
                      </div>
                      {isCurrent && <Badge tone="success">current</Badge>}
                      <div className="min-w-0 flex-1 text-xs text-slate-400">
                        <p className="text-slate-300">{row.note || row.published_by || '—'}</p>
                        <p className="mt-0.5 text-xs text-slate-600">
                          {formatDate(row.created_at)} · {relativeTime(row.created_at)}
                        </p>
                      </div>
                      <div className="flex shrink-0 items-center gap-2">
                        <Button size="sm" variant="ghost" onClick={() => openVersion(row.version)}>
                          {preview?.version === row.version ? 'Hide' : 'Inspect'}
                        </Button>
                        {!isCurrent &&
                          (confirming === row.version ? (
                            <>
                              <Button size="sm" variant="danger" loading={action.busy} onClick={() => rollback(row.version)}>
                                Confirm
                              </Button>
                              <Button size="sm" variant="ghost" onClick={() => setConfirming(null)}>
                                Cancel
                              </Button>
                            </>
                          ) : (
                            <Button
                              size="sm"
                              variant="secondary"
                              icon={<Undo2 className="h-3.5 w-3.5" />}
                              onClick={() => setConfirming(row.version)}
                            >
                              Roll back
                            </Button>
                          ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </CardBody>
        </Card>
      )}

      {preview && (
        <Card className="mt-4">
          <CardHeader title={`Version ${preview.version}`} description="Raw stored payload." />
          <CardBody>
            <pre className="max-h-96 overflow-auto scroll-thin rounded-lg bg-surface p-4 font-mono text-xs leading-relaxed text-slate-400">
              {JSON.stringify(preview.data, null, 2)}
            </pre>
          </CardBody>
        </Card>
      )}
    </div>
  )
}
