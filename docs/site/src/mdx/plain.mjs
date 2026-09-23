import { remark } from 'remark'
import remarkGfm from 'remark-gfm'
import remarkMdx from 'remark-mdx'
import { visit } from 'unist-util-visit'

const parser = remark().use(remarkMdx).use(remarkGfm)
const writer = remark().use(remarkGfm)

function clean(node) {
  if (node.type === 'mdxjsEsm') return []
  const allowed = { Property: ['name', 'type'], CodeGroup: ['title'] }
  if (
    node.attributes?.some(
      (attribute) =>
        attribute.type !== 'mdxJsxAttribute' ||
        !allowed[node.name]?.includes(attribute.name) ||
        typeof attribute.value !== 'string',
    )
  ) {
    throw new Error(`Unsupported MDX attributes in text export: ${node.name}`)
  }
  if (node.children) node.children = node.children.flatMap(clean)
  if (node.type === 'mdxJsxFlowElement') {
    const attrs = Object.fromEntries(
      node.attributes.map(({ name, value }) => [name, value]),
    )
    if (node.name === 'Property') {
      return [
        {
          type: 'paragraph',
          children: [
            {
              type: 'strong',
              children: [{ type: 'inlineCode', value: attrs.name }],
            },
            ...(attrs.type
              ? [
                  { type: 'text', value: ' — ' },
                  { type: 'inlineCode', value: attrs.type },
                ]
              : []),
          ],
        },
        ...node.children,
      ]
    }
    if (node.name === 'CodeGroup' && attrs.title) {
      return [
        {
          type: 'paragraph',
          children: [
            {
              type: 'strong',
              children: [{ type: 'text', value: attrs.title }],
            },
          ],
        },
        ...node.children,
      ]
    }
    if (['Row', 'Col', 'Properties', 'CodeGroup'].includes(node.name))
      return node.children
  }
  if (node.type === 'mdxJsxFlowElement' && node.name === 'Note') {
    return [{ type: 'blockquote', children: node.children }]
  }
  if (node.type.startsWith('mdx')) {
    throw new Error(`Unsupported MDX in text export: ${node.name ?? node.type}`)
  }
  if (node.type === 'code') node.meta = null
  return [node]
}

export function toMarkdown(source, basePath = '') {
  const tree = clean(parser.parse(source))[0]
  visit(tree, 'link', (node) => {
    if (node.url.startsWith('/') && !node.url.startsWith('//')) {
      node.url = basePath + node.url
    }
  })
  return writer.stringify(tree)
}
