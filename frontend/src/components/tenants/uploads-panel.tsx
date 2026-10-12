import { useRef, useState } from 'react'
import {
  FileText,
  FolderUp,
  Download,
  Eye,
  RefreshCw,
  Trash2,
  Upload,
} from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { FILE_MODULES, UPLOAD_ACCEPT, UPLOAD_TYPES_LABEL, MAX_UPLOAD_LABEL, formatBytes, openBlob, saveBlob, uploadsApi, type AdminFile } from '@/lib/uploads'
import { formatDate } from '@/lib/format'
import { cn } from '@/lib/cn'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

/**
 * Uploads is the tenant's own knowledge: FAQ documents, KB articles, brochure
 * PDFs and new-release sheets. Uploading feeds the bot's index, so this screen
 * says so plainly rather than pretending it is a generic file cabinet.
 */
export function UploadsPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()
  const inputRef = useRef<HTMLInputElement>(null)

  const [module, setModule] = useState<string>(FILE_MODULES[0].value)
  const [search, setSearch] = useState('')
  const [busyName, setBusyName] = useState<string | null>(null)

  const state = useAsync(
    (signal) => uploadsApi.list(tenantId, { module, search: search || undefined }, signal),
    [tenantId, module, search],
  )

  const activeModule = FILE_MODULES.find((m) => m.value === module) ?? FILE_MODULES[0]
  const canUpload = can(activeModule.permission)
  const canDelete = can('delete_files')
  const files = state.data ?? []

  const pick = () => inputRef.current?.click()

  const onFile = async (file: File | null) => {
    if (!file) return
    const result = await action.run(() => uploadsApi.upload(tenantId, file, module))
    if (result) {
      toast.push(`${file.name} uploaded (${result.chunks} chunks indexed)`)
      state.reload()
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  const remove = async (item: AdminFile) => {
    if (!window.confirm(`Delete ${item.name}? Its indexed content is removed too.`)) return
    const result = await action.run(() => uploadsApi.remove(tenantId, item.name))
    if (result) {
      toast.push(`${item.name} deleted`)
      state.reload()
    }
  }

  const fetchFile = async (item: AdminFile, download: boolean) => {
    setBusyName(item.name)
    try {
      const blob = await uploadsApi.blob(tenantId, item.name, download)
      if (download) saveBlob(blob, item.name)
      else openBlob(blob)
    } catch (err) {
      toast.push((err as Error).message, 'error')
    } finally {
      setBusyName(null)
    }
  }

  if (!can('view_files')) {
    return (
      <div>
        <PageHeader title="Uploads" />
        <Alert tone="warning" title="Not permitted">
          This screen needs the <strong>view_files</strong> permission.
        </Alert>
      </div>
    )
  }

  return (
    <div>
      <PageHeader
        title="Uploads"
        description="Documents the bot learns from. A successful upload is extracted, embedded and made searchable for this tenant."
        meta={state.data && <Badge tone="accent">{files.length} files</Badge>}
        actions={
          <>
            <Button variant="ghost" icon={<RefreshCw className={cn('h-4 w-4', state.loading && 'animate-spin')} />} onClick={state.reload}>
              Refresh
            </Button>
            {canUpload && (
              <Button variant="primary" icon={<Upload className="h-4 w-4" />} onClick={pick} loading={action.busy}>
                Upload file
              </Button>
            )}
          </>
        }
      />

      <input
        ref={inputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        className="hidden"
        onChange={(e) => void onFile(e.target.files?.[0] ?? null)}
      />

      <p className="mb-4 text-2xs text-slate-500">
        Supported formats: {UPLOAD_TYPES_LABEL} · Max {MAX_UPLOAD_LABEL} per file
      </p>

      {action.error && (
        <Alert tone="danger" title="Upload failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-1.5">
          {FILE_MODULES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => setModule(m.value)}
              className={cn(
                'rounded-lg px-3 py-1.5 text-xs font-medium transition',
                module === m.value
                  ? 'bg-accent-100 text-accent-800'
                  : 'text-slate-400 hover:bg-surface-panel hover:text-slate-200',
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter by name…"
          className="w-56"
        />
      </div>

      {!canUpload && (
        <Alert tone="info" className="mb-4">
          You can view {activeModule.label} files, but uploading them needs the{' '}
          <strong>{activeModule.permission}</strong> permission.
        </Alert>
      )}

      <Card>
        <CardHeader title={`${activeModule.label} files`} icon={<FolderUp className="h-4 w-4" />} />
        {state.loading && !files.length ? (
          <LoadingBlock label="Loading files…" />
        ) : state.error ? (
          <CardBody>
            <Alert tone="danger" title="Could not load files">
              {state.error}
            </Alert>
          </CardBody>
        ) : files.length === 0 ? (
          <EmptyState
            title={`No ${activeModule.label.toLowerCase()} files`}
            description={
              canUpload
                ? 'Upload a document and the bot will be able to answer from it.'
                : 'Nothing has been uploaded for this module yet.'
            }
            icon={<FileText className="h-6 w-6" />}
          />
        ) : (
          <ul className="divide-y divide-surface-line">
            {files.map((item) => (
              <li key={item.id} className="flex items-center gap-3 px-5 py-3.5">
                <FileText className="h-4 w-4 shrink-0 text-accent-400" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium text-slate-100">{item.name}</p>
                  <p className="mt-0.5 text-2xs text-slate-500">
                    {(item.ext || 'file').toUpperCase()} · {formatBytes(item.size)} · {formatDate(item.created_at)}
                  </p>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    size="icon"
                    variant="ghost"
                    title="Preview"
                    loading={busyName === item.name}
                    onClick={() => void fetchFile(item, false)}
                  >
                    <Eye className="h-4 w-4" />
                  </Button>
                  <Button size="icon" variant="ghost" title="Download" onClick={() => void fetchFile(item, true)}>
                    <Download className="h-4 w-4" />
                  </Button>
                  {canDelete && (
                    <Button
                      size="icon"
                      variant="ghost"
                      title="Delete"
                      onClick={() => void remove(item)}
                      className="text-rose-400 hover:text-rose-300"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  )
}
