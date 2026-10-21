import { useRef, useState } from 'react'
import {
  FileText,
  FolderUp,
  Download,
  Eye,
  RefreshCw,
  Trash2,
  Upload,
  Sparkles,
  CheckCircle2,
  Package,
  Layers,
  ArrowRight,
  Bot,
  Compass,
} from 'lucide-react'
import { useAction, useAsync } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import {
  FILE_MODULES,
  UPLOAD_ACCEPT,
  UPLOAD_TYPES_LABEL,
  MAX_UPLOAD_LABEL,
  formatBytes,
  openBlob,
  saveBlob,
  uploadsApi,
  type AdminFile,
  type BifurcationResult,
} from '@/lib/uploads'
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
 * Uploads is the tenant's own knowledge hub: FAQ documents, KB articles,
 * brochure PDFs, and new-release sheets.
 *
 * Equipped with Zero-Touch Auto-Bifurcation: Client administrators can upload all
 * PDFs and Word collateral in bulk, and the backend automatically parses, classifies,
 * and configures the tenant profile, WhatsApp menu, offerings catalog, intents,
 * and vector RAG embeddings without any manual data entry.
 */
export function UploadsPanel({ tenantId }: { tenantId: string }) {
  const { can } = useAuth()
  const toast = useToast()
  const action = useAction()
  const inputRef = useRef<HTMLInputElement>(null)
  const autoInputRef = useRef<HTMLInputElement>(null)

  const [module, setModule] = useState<string>(FILE_MODULES[0].value)
  const [search, setSearch] = useState('')
  const [busyName, setBusyName] = useState<string | null>(null)
  const [bifurcating, setBifurcating] = useState(false)
  const [bifurcationResult, setBifurcationResult] = useState<BifurcationResult | null>(null)

  const state = useAsync(
    (signal) => uploadsApi.list(tenantId, { module, search: search || undefined }, signal),
    [tenantId, module, search],
  )

  const activeModule = FILE_MODULES.find((m) => m.value === module) ?? FILE_MODULES[0]
  const canUpload = can(activeModule.permission)
  const canDelete = can('delete_files')
  const files = state.data ?? []

  const pickSingle = () => inputRef.current?.click()
  const pickAutoBatch = () => autoInputRef.current?.click()

  const onSingleFile = async (file: File | null) => {
    if (!file) return
    const result = await action.run(() => uploadsApi.upload(tenantId, file, module))
    if (result) {
      toast.push(`${file.name} uploaded (${result.chunks} chunks indexed)`)
      state.reload()
    }
    if (inputRef.current) inputRef.current.value = ''
  }

  const onAutoBatchFiles = async (fileList: FileList | null) => {
    if (!fileList || fileList.length === 0) return
    const batch = Array.from(fileList)
    setBifurcating(true)
    setBifurcationResult(null)
    try {
      toast.push(`Analyzing & bifurcating ${batch.length} documents...`)
      const res = await uploadsApi.autoBifurcate(tenantId, batch, true)
      setBifurcationResult(res)
      toast.push(`Auto-bifurcation complete! All components configured & published.`)
      state.reload()
    } catch (err) {
      toast.push((err as Error).message || 'Auto-bifurcation failed', 'error')
    } finally {
      setBifurcating(false)
      if (autoInputRef.current) autoInputRef.current.value = ''
    }
  }

  const onBifurcateExisting = async () => {
    if (files.length === 0) {
      toast.push('No uploaded files available to bifurcate.', 'error')
      return
    }
    setBifurcating(true)
    setBifurcationResult(null)
    try {
      toast.push(`Bifurcating existing files in library...`)
      const res = await uploadsApi.bifurcateExisting(tenantId)
      setBifurcationResult(res)
      toast.push(`Auto-bifurcation complete! System updated.`)
      state.reload()
    } catch (err) {
      toast.push((err as Error).message || 'Bifurcation failed', 'error')
    } finally {
      setBifurcating(false)
    }
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
      <div className="min-w-0">
        <PageHeader title="Uploads" />
        <Alert tone="warning" title="Not permitted">
          This screen needs the <strong>view_files</strong> permission.
        </Alert>
      </div>
    )
  }

  return (
    <div className="min-w-0">
      <PageHeader
        title="Uploads & Auto-Configurator"
        description="Upload client documents (PDF, Word, Excel). The backend automatically bifurcates data and configures the Profile, Menu, Intents, Catalog, and Vector RAG."
        meta={state.data && <Badge tone="accent">{files.length} files</Badge>}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="ghost"
              icon={<RefreshCw className={cn('h-4 w-4', state.loading && 'animate-spin')} />}
              onClick={state.reload}
            >
              Refresh
            </Button>
            {files.length > 0 && (
              <Button
                variant="secondary"
                icon={<Sparkles className="h-4 w-4 text-accent-400" />}
                onClick={() => void onBifurcateExisting()}
                loading={bifurcating}
              >
                Bifurcate Existing
              </Button>
            )}
            {canUpload && (
              <Button
                variant="primary"
                icon={<Sparkles className="h-4 w-4" />}
                onClick={pickAutoBatch}
                loading={bifurcating}
              >
                Auto-Configure From Files
              </Button>
            )}
          </div>
        }
      />

      {/* Hidden file inputs */}
      <input
        ref={inputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        className="hidden"
        onChange={(e) => void onSingleFile(e.target.files?.[0] ?? null)}
      />
      <input
        ref={autoInputRef}
        type="file"
        accept={UPLOAD_ACCEPT}
        multiple
        className="hidden"
        onChange={(e) => void onAutoBatchFiles(e.target.files)}
      />

      {/* Zero-Touch Document Intake Card */}
      <Card className="mb-6 border-accent-500/30 bg-accent-950/20">
        <CardHeader
          title="Zero-Touch Document Ingestion & Auto-Bifurcation"
          icon={<Sparkles className="h-4 w-4 text-accent-400" />}
          actions={
            <Button
              variant="primary"
              size="sm"
              icon={<Upload className="h-4 w-4" />}
              loading={bifurcating}
              onClick={pickAutoBatch}
            >
              Upload All PDF & Word Files
            </Button>
          }
        />
        <CardBody className="space-y-3">
          <p className="text-xs text-slate-300">
            Upload your company profile, brochures, product sheets, FAQs, and policy documents in bulk.
            The backend engine extracts text, understands the context, and automatically puts everything into its place:
          </p>

          <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-4">
            <div className="rounded-lg border border-surface-line bg-surface-panel/80 p-3">
              <div className="flex items-center gap-2 font-medium text-xs text-slate-200">
                <Bot className="h-4 w-4 text-emerald-400" />
                <span>1. Brand & Persona</span>
              </div>
              <p className="mt-1 text-2xs text-slate-400">
                Name, Bot identity, Tagline, Support Phone/Email & Operating Hours configured in Profile.
              </p>
            </div>

            <div className="rounded-lg border border-surface-line bg-surface-panel/80 p-3">
              <div className="flex items-center gap-2 font-medium text-xs text-slate-200">
                <Compass className="h-4 w-4 text-sky-400" />
                <span>2. WhatsApp Menu</span>
              </div>
              <p className="mt-1 text-2xs text-slate-400">
                3 to 6 interactive buttons & list drawer items formatted under Meta WhatsApp API length limits.
              </p>
            </div>

            <div className="rounded-lg border border-surface-line bg-surface-panel/80 p-3">
              <div className="flex items-center gap-2 font-medium text-xs text-slate-200">
                <Package className="h-4 w-4 text-amber-400" />
                <span>3. Catalog Offerings</span>
              </div>
              <p className="mt-1 text-2xs text-slate-400">
                Products, packages, properties, and services extracted and populated into the database.
              </p>
            </div>

            <div className="rounded-lg border border-surface-line bg-surface-panel/80 p-3">
              <div className="flex items-center gap-2 font-medium text-xs text-slate-200">
                <Layers className="h-4 w-4 text-violet-400" />
                <span>4. Vector RAG Search</span>
              </div>
              <p className="mt-1 text-2xs text-slate-400">
                Markdown knowledge articles, text chunks, and FAISS vector embeddings indexed immediately.
              </p>
            </div>
          </div>
        </CardBody>
      </Card>

      {/* Auto-Bifurcation Result Banner */}
      {bifurcationResult && (
        <Card className="mb-6 border-emerald-500/40 bg-emerald-950/20">
          <CardHeader
            title="Auto-Bifurcation Successful & Published Live"
            icon={<CheckCircle2 className="h-5 w-5 text-emerald-400" />}
            actions={
              <Badge tone="accent">
                Version {bifurcationResult.version || 1} Live
              </Badge>
            }
          />
          <CardBody className="space-y-4">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <div className="rounded-md border border-emerald-500/20 bg-surface-base/80 p-3">
                <p className="text-2xs text-slate-400">Brand Configured</p>
                <p className="font-semibold text-sm text-slate-100">{bifurcationResult.brand?.name}</p>
                <p className="text-2xs text-slate-400">{bifurcationResult.brand?.bot_name}</p>
                <p className="mt-1 text-2xs text-emerald-400">Vertical: {bifurcationResult.vertical}</p>
              </div>

              <div className="rounded-md border border-emerald-500/20 bg-surface-base/80 p-3">
                <p className="text-2xs text-slate-400">Catalog Offerings</p>
                <p className="font-semibold text-lg text-emerald-400">{bifurcationResult.offerings_created}</p>
                <p className="truncate text-2xs text-slate-300">
                  {bifurcationResult.offerings_sample?.join(', ') || 'Populated into catalog'}
                </p>
              </div>

              <div className="rounded-md border border-emerald-500/20 bg-surface-base/80 p-3">
                <p className="text-2xs text-slate-400">WhatsApp Navigation</p>
                <p className="font-semibold text-lg text-emerald-400">{bifurcationResult.menu_buttons_count} Options</p>
                <p className="text-2xs text-slate-300">Formatted for WhatsApp API</p>
              </div>

              <div className="rounded-md border border-emerald-500/20 bg-surface-base/80 p-3">
                <p className="text-2xs text-slate-400">Vector Search / RAG</p>
                <p className="font-semibold text-lg text-emerald-400">{bifurcationResult.kb_chunks_indexed} Chunks</p>
                <p className="text-2xs text-slate-300">FAISS & BM25 Ready</p>
              </div>
            </div>

            {/* Quick jump navigation links */}
            <div className="flex flex-wrap items-center gap-2 pt-2 border-t border-surface-line">
              <span className="text-2xs text-slate-400">Inspect configured sections:</span>
              <a
                href={`#/tenants/${tenantId}/offerings`}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 text-2xs font-medium bg-surface-panel hover:bg-surface-line text-slate-200 transition"
              >
                <Package className="h-3 w-3 text-amber-400" />
                View Offerings Catalog
              </a>
              <a
                href={`#/tenants/${tenantId}/menu`}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 text-2xs font-medium bg-surface-panel hover:bg-surface-line text-slate-200 transition"
              >
                <Compass className="h-3 w-3 text-sky-400" />
                View WhatsApp Menu
              </a>
              <a
                href={`#/tenants/${tenantId}/profile`}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 text-2xs font-medium bg-surface-panel hover:bg-surface-line text-slate-200 transition"
              >
                <Bot className="h-3 w-3 text-emerald-400" />
                View Profile
              </a>
              <a
                href={`#/tenants/${tenantId}/test`}
                className="inline-flex items-center gap-1 rounded px-2.5 py-1 text-2xs font-medium bg-accent-100 hover:bg-accent-200 text-accent-800 transition"
              >
                <ArrowRight className="h-3 w-3" />
                Test in Sandbox
              </a>
            </div>
          </CardBody>
        </Card>
      )}

      {/* Traditional Upload & Existing Files Section */}
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
        <div className="flex items-center gap-2">
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter files by name…"
            className="w-full sm:w-56"
          />
          {canUpload && (
            <Button variant="secondary" size="sm" icon={<Upload className="h-3.5 w-3.5" />} onClick={pickSingle}>
              Upload Single
            </Button>
          )}
        </div>
      </div>

      <p className="mb-4 text-2xs text-slate-500">
        Supported formats: {UPLOAD_TYPES_LABEL} · Max {MAX_UPLOAD_LABEL} per file
      </p>

      {action.error && (
        <Alert tone="danger" title="Upload failed" className="mb-4">
          {action.error}
        </Alert>
      )}

      {!canUpload && (
        <Alert tone="info" className="mb-4">
          You can view {activeModule.label} files, but uploading them needs the{' '}
          <strong>{activeModule.permission}</strong> permission.
        </Alert>
      )}

      <Card className="min-w-0">
        <CardHeader title={`${activeModule.label} files (${files.length})`} icon={<FolderUp className="h-4 w-4" />} />
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
                ? 'Upload your PDF or Word documents to auto-configure the bot or index knowledge.'
                : 'Nothing has been uploaded for this module yet.'
            }
            icon={<FileText className="h-6 w-6" />}
          />
        ) : (
          <ul className="divide-y divide-surface-line">
            {files.map((item) => (
              <li
                key={item.id}
                className="flex flex-col gap-2 px-5 py-3.5 sm:flex-row sm:items-center sm:gap-3"
              >
                <div className="flex min-w-0 items-start gap-3 sm:flex-1 sm:items-center">
                  <FileText className="mt-0.5 h-4 w-4 shrink-0 text-accent-400 sm:mt-0" />
                  <div className="min-w-0 flex-1">
                    <p className="break-all text-sm font-medium text-slate-100 sm:truncate" title={item.name}>
                      {item.name}
                    </p>
                    <p className="mt-0.5 text-2xs text-slate-500">
                      {(item.ext || 'file').toUpperCase()} · {formatBytes(item.size)} · {formatDate(item.created_at)}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1 pl-7 sm:pl-0">
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
