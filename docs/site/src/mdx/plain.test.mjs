import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import {
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { toMarkdown } from './plain.mjs'

test('exports content, tables and every code tab without MDX presentation', () => {
  const source = `export const metadata = { title: 'Guide' }

# Guide

<Note>

Keep this note.

</Note>

| Field | Meaning |
| --- | --- |
| score | Result |

<CodeGroup>

\`\`\`sh {{ title: 'Shell' }}
echo "hello"
\`\`\`

\`\`\`python
print("hello")
\`\`\`

</CodeGroup>
`
  const result = toMarkdown(source)
  assert.match(result, /^# Guide/)
  assert.match(result, /> Keep this note\./)
  assert.match(result, /\| score\s+\| Result/)
  assert.match(result, /```sh\necho "hello"\n```/)
  assert.match(result, /```python\nprint\("hello"\)\n```/)
  assert.doesNotMatch(result, /export const|CodeGroup|<Note>|title: 'Shell'/)
})

test('rejects components and expressions whose text cannot be exported', () => {
  for (const source of [
    '# Guide\n\n<Example />',
    '# Guide\n\nValue: {value}',
    '# Guide\n\n<CodeGroup title="Example">\n\nText.\n\n</CodeGroup>',
  ]) {
    assert.throws(() => toMarkdown(source), /Unsupported MDX/)
  }
})

test('generates text and discovery links for root and nested pages', () => {
  const root = mkdtempSync(join(tmpdir(), 'docs-export-'))
  try {
    for (const [route, title] of [
      ['', 'Quickstart'],
      ['guide/', 'Guide'],
    ]) {
      mkdirSync(join(root, 'src/app', route), { recursive: true })
      mkdirSync(join(root, 'out', route), { recursive: true })
      writeFileSync(
        join(root, 'src/app', route, 'page.mdx'),
        `# ${title}\n\nContent.\n`,
      )
      writeFileSync(join(root, 'out', route, 'index.html'), '<html></html>')
    }
    execFileSync(
      process.execPath,
      [
        fileURLToPath(
          new URL('../../scripts/export-markdown.mjs', import.meta.url),
        ),
      ],
      { cwd: root },
    )
    assert.equal(
      readFileSync(join(root, 'out/index.md'), 'utf8'),
      '# Quickstart\n\nContent.\n',
    )
    assert.equal(
      readFileSync(join(root, 'out/guide/index.md'), 'utf8'),
      '# Guide\n\nContent.\n',
    )
    const index = readFileSync(join(root, 'out/llms.txt'), 'utf8')
    assert.match(index, /\[Quickstart\]\(\.\/index.md\)/)
    assert.match(index, /\[Guide\]\(\.\/guide\/index.md\)/)
  } finally {
    rmSync(root, { recursive: true, force: true })
  }
})
