import { useState } from 'react'
import { Pencil, Plus, Save, Send, Trash2, X } from 'lucide-react'
import { tenantsApi } from '@/lib/tenants'
import { useAction } from '@/lib/hooks'
import { FEATURE_FLAGS, type IntentSpec } from '@/lib/types'
import { FEATURE_LABELS } from '@/lib/verticals'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tags'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { useResolved } from '@/components/tenants/hooks'

export function IntentsEditor({ tenantId }: { tenantId: string }) {
  const { data, loading, error, reload } = useResolved(tenantId)
  const action = useAction()
  const toast = useToast()
  const [draft, setDraft] = useState<IntentSpec | null>(null)
  const [editing, setEditing] = useState(false)
  const [validation, setValidation] = useState<string[]>([])

  const all = data ? [...data.active_intents, ...data.inactive_intents] : []

  const save = async (thenPublish: boolean) => {
    if (!draft) return
    const body: any = {
      answer: draft.answer ?? null,
      keywords: draft.keywords ?? [],
      examples: draft.examples ?? [],
      enabled: draft.enabled ?? true,
      flow: draft.flow ?? null,
      requires_feature: draft.requires_feature ?? null,
    }
    const saved = await action.run(() => tenantsApi.saveIntent(tenantId, draft.name, body))
    if (!saved) return
    setValidation(saved.validation ?? [])
    if (!thenPublish) {
      toast.push('Intent saved to draft.')
      reload()
      return
    }
    if ((saved.validation ?? []).length > 0) {
      toast.push('Draft has validation warnings — fix before publishing.')
      return
    }
    const pub = await action.run(() => tenantsApi.publish(tenantId))
    if (pub) {
      if (pub.status === 'pending_approval') {
        toast.push(pub.message ?? 'Change sent for approval.')
      } else {
        toast.push(`Published version ${pub.version}`)
      }
      reload()
      setDraft(null)
      setEditing(false)
    }
  }

  const remove = async (name: string) => {
    if (!confirm(`Delete intent "${name}"?`)) return
    const body: any = { __remove__: true }
    const saved = await action.run(() => tenantsApi.saveIntent(tenantId, name, body))
    if (!saved) return
    const pub = await action.run(() => tenantsApi.publish(tenantId))
    if (pub) {
      if (pub.status === 'pending_approval') toast.push(pub.message ?? 'Change sent for approval.')
      else toast.push(`Published version ${pub.version}`)
      reload()
    }
  }

  const startAdd = () => {
    setDraft({
      name: '',
      examples: [],
      keywords: [],
      requires_feature: null,
      flow: null,
      answer: '',
      enabled: true,
    })
    setEditing(true)
  }

  const startEdit = (i: IntentSpec) => {
    setDraft({ ...i, examples: [...(i.examples ?? [])], keywords: [...(i.keywords ?? [])] })
    setEditing(true)
  }

  if (loading) return <LoadingBlock label="Loading intents…" />
  if (error || !data) return <Alert tone="danger" title="Could not load intents">{error}</Alert>

  return (
    <div>
      <PageHeader
        title="Intents Editor"
        description="Add, edit, enable/disable intents. Changes go to draft and need publishing."
        actions={
          <Button size="sm" variant="primary" icon={<Plus className="h-4 w-4" />} onClick={startAdd}>
            Add intent
          </Button>
        }
      />

      {editing && draft && (
        <Card className="mb-4">
          <CardHeader
            title={draft.name ? `Edit ${draft.name}` : 'Add new intent'}
            actions={<Button size="sm" variant="ghost" onClick={() => { setEditing(false); setDraft(null) }} icon={<X className="h-4 w-4" />} />}
          />
          <CardBody className="space-y-4">
            <Input label="Name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} disabled={Boolean(all.find((a) => a.name === draft.name) && !editing)} placeholder="intent_name" />
            <Textarea label="Answer" rows={4} value={draft.answer ?? ''} onChange={(e) => setDraft({ ...draft, answer: e.target.value })} />
            <TagInput value={draft.keywords ?? []} onChange={(k) => setDraft({ ...draft, keywords: k })} placeholder="Keywords" />
            <TagInput value={draft.examples ?? []} onChange={(e) => setDraft({ ...draft, examples: e })} placeholder="Examples" />
            <div className="grid gap-4 sm:grid-cols-3">
              <Select label="Requires feature" value={draft.requires_feature ?? ''} onChange={(e) => setDraft({ ...draft, requires_feature: e.target.value || null })}>
                <option value="">None</option>
                {FEATURE_FLAGS.map((f) => (
                  <option key={f} value={f}>{FEATURE_LABELS[f]?.label ?? f}</option>
                ))}
              </Select>
              <Input label="Flow" value={draft.flow ?? ''} onChange={(e) => setDraft({ ...draft, flow: e.target.value || '' })} placeholder="flow_name" />
              <Switch checked={draft.enabled ?? true} onChange={(en) => setDraft({ ...draft, enabled: en })} label="Enabled" />
            </div>
            <div className="flex gap-2">
              <Button size="sm" variant="primary" onClick={() => save(false)} loading={action.busy} icon={<Save className="h-4 w-4" />}>Save draft</Button>
              <Button size="sm" variant="secondary" onClick={() => save(true)} loading={action.busy} icon={<Send className="h-4 w-4" />}>Save & publish</Button>
            </div>
            {validation.length > 0 && <Alert tone="warning">{validation.join(', ')}</Alert>}
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader title="All intents" />
        <CardBody className="space-y-2">
          {all.map((i) => (
            <div key={i.name} className="rounded-lg p-3 ring-1 ring-inset bg-surface-panel ring-surface-line">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium">{i.name}</span>
                  {i.enabled ? <Badge tone="success">enabled</Badge> : <Badge tone="muted">disabled</Badge>}
                  {i.flow && <Badge tone="accent">flow:{i.flow}</Badge>}
                  {i.requires_feature && <Badge tone="neutral">needs:{i.requires_feature}</Badge>}
                </div>
                <div className="flex gap-1">
                  <Button size="sm" variant="ghost" onClick={() => startEdit(i)} icon={<Pencil className="h-4 w-4" />} />
                  <Button size="sm" variant="ghost" onClick={() => remove(i.name)} icon={<Trash2 className="h-4 w-4" />} />
                </div>
              </div>
              {i.keywords?.length > 0 && <p className="text-xs text-slate-500 mt-1">Keywords: {i.keywords.join(', ')}</p>}
              {i.examples?.length > 0 && <p className="text-xs text-slate-500 mt-1">Examples: {i.examples.join(', ')}</p>}
              {i.answer && <p className="text-xs text-slate-500 mt-1 truncate">{i.answer}</p>}
            </div>
          ))}
        </CardBody>
      </Card>
    </div>
  )
}
