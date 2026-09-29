import clsx from 'clsx'

export function Logo({ className }: { className?: string }) {
  return (
    <span
      aria-label="Local Offline Assessor for FAIR (LOAF)"
      className={clsx(
        'inline-flex items-center font-semibold tracking-tight text-brand-700 dark:text-brand-400',
        className,
      )}
    >
      LOAF
    </span>
  )
}
