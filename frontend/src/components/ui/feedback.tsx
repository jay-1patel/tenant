  import type { ReactNode } from 'react'
  import { AlertCircle, CheckCircle2, Info, Loader2, X } from 'lucide-react'
  import { cn } from '@/lib/cn'

  export function Spinner({ className }: { className?: string }) {
    return <Loader2 className={cn('h-5 w-5 animate-spin text-accent-400', className)} />
  }

  export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
    return (
      <div className="flex items-center justify-center gap-3 py-12 text-sm text-slate-500">
        <Spinner className="h-4 w-4" />
        {label}
      </div>
    )
  }

  export function Alert({
    tone = 'info',
    title,
    children,
    className,
  }: {
    tone?: 'info' | 'success' | 'warning' | 'danger'
    title?: ReactNode
    children?: ReactNode
    className?: string
  }) {
    const map = {
      info: { cls: 'bg-accent-50 text-accent-900 ring-accent-200', Icon: Info },
      success: { cls: 'bg-emerald-50 text-emerald-900 ring-emerald-200', Icon: CheckCircle2 },
      warning: { cls: 'bg-amber-50 text-amber-900 ring-amber-200', Icon: AlertCircle },
      danger: { cls: 'bg-rose-50 text-rose-900 ring-rose-200', Icon: AlertCircle },
    }[tone]
    const Icon = map.Icon
    return (
      <div className={cn('flex gap-2.5 rounded-lg px-3.5 py-3 text-xs leading-relaxed ring-1 ring-inset', map.cls, className)}>
        <Icon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0">
          {title && <p className="font-semibold">{title}</p>}
          {children && <div className={cn(title && 'mt-1', 'break-words')}>{children}</div>}
        </div>
      </div>
    )
  }

  export function EmptyState({
    title,
    description,
    action,
    icon,
  }: {
    title: string
    description?: ReactNode
    action?: ReactNode
    icon?: ReactNode
  }) {
    return (
      <div className="flex flex-col items-center justify-center gap-3 px-6 py-14 text-center">
        {icon && <div className="text-slate-600">{icon}</div>}
        <div>
          <p className="text-sm font-medium text-slate-200">{title}</p>
          {description && <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-500">{description}</p>}
        </div>
        {action}
      </div>
    )
  }

  /**
 * Inline toast notification with an optional dismiss button. Composes the
 * Alert's tone styling, so the two always look consistent.
 */
export function Toast({
  tone = 'info',
  title,
  children,
  onDismiss,
  className,
}: {
  tone?: 'info' | 'success' | 'warning' | 'danger'
  title?: ReactNode
  children?: ReactNode
  onDismiss?: () => void
  className?: string
}) {
  return (
    <div role="status" className={cn('flex items-start gap-3', className)}>
      <div className="min-w-0 flex-1">
        <Alert tone={tone} title={title}>{children}</Alert>
      </div>
      {onDismiss && (
        <button
          type="button"
          onClick={onDismiss}
          aria-label="Dismiss notification"
          className="mt-0.5 shrink-0 rounded text-slate-400 transition hover:text-slate-200"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      )}
    </div>
  )
}

export function Skeleton({ className }: { className?: string }) {
    return <div className={cn('animate-pulse rounded-md bg-surface-panel', className)} />
  }
