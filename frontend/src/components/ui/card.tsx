import type { HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Card({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-xl bg-surface-raised shadow-sm ring-1 ring-surface-line', className)}
      {...rest}
    />
  )
}

export function CardHeader({
  title,
  description,
  actions,
  icon,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  icon?: ReactNode
  className?: string
}) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-4 border-b border-surface-line px-5 py-4', className)}>
      <div className="flex min-w-0 flex-1 items-start gap-3">
        {icon && <span className="mt-0.5 text-accent-400">{icon}</span>}
        <div className="min-w-0">
          <h2 className="truncate text-sm font-semibold text-slate-100">{title}</h2>
          {description && <p className="mt-1 text-xs leading-relaxed text-slate-400">{description}</p>}
        </div>
      </div>
      {actions && (
        <div className="flex w-full min-w-0 flex-wrap items-center justify-end gap-2 lg:w-auto">{actions}</div>
      )}
    </div>
  )
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-5 py-4', className)} {...rest} />
}

export function SectionTitle({ children, hint }: { children: ReactNode; hint?: ReactNode }) {
  return (
    <div className="mb-3">
      <h3 className="text-xs font-semibold uppercase tracking-wider text-slate-400">{children}</h3>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}
