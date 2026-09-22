export function Footer() {
  return (
    <footer className="mx-auto flex w-full max-w-3xl flex-wrap items-center justify-between gap-3 border-t border-brand-950/10 py-8 text-xs text-zinc-500 dark:border-white/10 dark:text-zinc-400">
      <span>fair-offline-assessor</span>
      <a
        href="https://github.com/akeldamas/fair-offline-assessor/issues"
        className="hover:text-brand-700 dark:hover:text-brand-300"
      >
        Report an issue
      </a>
    </footer>
  )
}
