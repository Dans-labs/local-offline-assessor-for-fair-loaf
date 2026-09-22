import { remark } from 'remark'
import remarkGfm from 'remark-gfm'
import remarkMdx from 'remark-mdx'

const parser = remark().use(remarkMdx).use(remarkGfm)
const writer = remark().use(remarkGfm)

function clean(node) {
  if (node.type === 'mdxjsEsm') return []
  if (node.attributes?.length) {
    throw new Error(`Unsupported MDX attributes in text export: ${node.name}`)
  }
  if (node.children) node.children = node.children.flatMap(clean)
  if (node.type === 'mdxJsxFlowElement' && node.name === 'CodeGroup')
    return node.children
  if (node.type === 'mdxJsxFlowElement' && node.name === 'Note') {
    return [{ type: 'blockquote', children: node.children }]
  }
  if (node.type.startsWith('mdx')) {
    throw new Error(`Unsupported MDX in text export: ${node.name ?? node.type}`)
  }
  if (node.type === 'code') node.meta = null
  return [node]
}

export function toMarkdown(source) {
  return writer.stringify(clean(parser.parse(source))[0])
}
