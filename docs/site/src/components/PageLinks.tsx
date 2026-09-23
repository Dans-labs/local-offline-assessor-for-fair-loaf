'use client'

import { usePathname } from 'next/navigation'

export function PageLinks() {
  const pathname = usePathname().replace(/\/$/, '')
  const basePath = process.env.NEXT_PUBLIC_BASE_PATH || ''
  const markdown = `${basePath}${pathname}/index.md`

  return (
    <div className="mx-auto mb-8 flex w-full max-w-7xl items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
      <link rel="alternate" type="text/markdown" href={markdown} />
      <a
        href={markdown}
        className="transition hover:text-brand-700 dark:hover:text-brand-300"
      >
        View as Markdown
      </a>
    </div>
  )
}
