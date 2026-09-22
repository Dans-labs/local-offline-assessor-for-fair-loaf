import glob from 'fast-glob'
import { access, readFile, writeFile } from 'node:fs/promises'
import path from 'node:path'

import { toMarkdown } from '../src/mdx/plain.mjs'

const pages = (await glob('**/page.mdx', { cwd: 'src/app' })).sort()
const links = []

for (const page of pages) {
  const route = page.replace(/page\.mdx$/, '')
  const markdown = toMarkdown(
    await readFile(path.join('src/app', page), 'utf8'),
  )
  const title = markdown.match(/^# (.+)$/m)?.[1]
  if (!title) throw new Error(`Missing page heading: ${page}`)
  await access(path.join('out', route, 'index.html'))
  await writeFile(path.join('out', route, 'index.md'), markdown)
  links.push(`- [${title}](./${route}index.md)`)
}

await writeFile(
  'out/llms.txt',
  '# fair-offline-assessor\n\n' +
    '> Offline FAIR assessment of supplied JSON-LD dataset metadata.\n\n' +
    '## Documentation\n\n' +
    links.join('\n') +
    '\n',
)
