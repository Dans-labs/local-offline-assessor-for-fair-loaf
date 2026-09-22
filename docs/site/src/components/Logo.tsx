import clsx from 'clsx'

export function Logo({ className }: { className?: string }) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-2 font-semibold tracking-tight text-brand-950 dark:text-white',
        className,
      )}
    >
      <span className="text-brand-700 dark:text-brand-400">FAIR</span>
      <span>offline assessor</span>
    </span>
  )
}
