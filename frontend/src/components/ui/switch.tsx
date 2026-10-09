import type { ReactNode } from 'react'
import { cn } from '@/lib/cn'

export function Switch({
  checked,
  onChange,
  label,
  description,
  disabled,
  size = 'md',
  className,
  ariaLabel,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label?: ReactNode
  description?: ReactNode
  disabled?: boolean
  size?: 'sm' | 'md'
  className?: string
  ariaLabel?: string
}) {
  const track = size === 'sm' ? 'h-4.5 w-8' : 'h-5 w-9'
  const knob = size === 'sm' ? 'h-3.5 w-3.5' : 'h-4 w-4'
  const shift = size === 'sm' ? 'translate-x-3.5' : 'translate-x-4'

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      disabled={disabled}
      onClick={() => onChange(!checked)}
      className={cn(
        'group flex items-start gap-3 text-left disabled:cursor-not-allowed disabled:opacity-50',
        label ? 'w-full' : 'w-auto',
        className,
      )}
    >
      <span
        className={cn(
          'relative mt-0.5 shrink-0 rounded-full transition-colors',
          track,
          checked ? 'bg-accent-600' : 'bg-surface-line',
        )}
      >
        <span
          className={cn(
            'absolute left-0.5 top-1/2 -translate-y-1/2 rounded-full bg-surface-raised shadow-sm ring-1 ring-slate-300 transition-transform',
            knob,
            checked && shift,
          )}
        />
      </span>
      {label && (
        <span className="min-w-0">
          <span className="block text-sm text-slate-200 group-hover:text-slate-100">{label}</span>
          {description && <span className="mt-0.5 block text-xs leading-relaxed text-slate-500">{description}</span>}
        </span>
      )}
    </button>
  )
}

export function Checkbox({
  checked,
  onChange,
  label,
  description,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: ReactNode
  description?: ReactNode
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 text-sm">
      <span
        className={cn(
          'mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border transition',
          checked ? 'border-accent-500 bg-accent-600' : 'border-surface-line bg-surface-raised',
        )}
      >
        {checked && (
          <svg viewBox="0 0 12 12" className="h-3 w-3 text-white" fill="none">
            <path d="M2 6.2 4.7 9 10 3.4" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
          </svg>
        )}
      </span>
      <input type="checkbox" className="sr-only" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span className="min-w-0">
        <span className="block text-slate-200">{label}</span>
        {description && <span className="mt-0.5 block text-xs text-slate-500">{description}</span>}
      </span>
    </label>
  )
}
