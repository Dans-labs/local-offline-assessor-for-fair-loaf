import clsx from 'clsx'

export function Prose<T extends React.ElementType = 'div'>({
  as,
  className,
  ...props
}: Omit<React.ComponentPropsWithoutRef<T>, 'as' | 'className'> & {
  as?: T
  className?: string
}) {
  let Component = as ?? 'div'

  return (
    <Component
      className={clsx(
        'docs-prose mx-auto prose w-full max-w-7xl dark:prose-invert',
        className,
      )}
      {...props}
    />
  )
}
