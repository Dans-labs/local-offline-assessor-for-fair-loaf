# Documentation site

Requires Node.js 22+ and npm. Run from this directory:

```sh
npm ci
npm run dev
```

Open the local URL printed by the command.

## Edit pages

Pages are in `src/app/**/page.mdx`; navigation is in
`src/components/Navigation.tsx`. MDX is Markdown with components for layouts and
code examples. Follow `src/app/reference/page.mdx` when using those components.

Write for someone using the library without knowledge of its implementation:

- Say what the user supplies, what the assessor checks and what the result means.
- Explain necessary terms on first use. Use plain descriptions such as
  “the assessor's original results” for `raw`.
- Keep API names exact, and explain them in ordinary language.
- Put code-generation and version-update instructions in the
  [maintainer guide](../maintaining.md).
- Run examples and check that any shown output matches.

## Check changes

```sh
npm test
npm run lint
npm run check
npm run format
npm run build
```

The build writes the website to `out/`. It also creates a Markdown copy of every
page and an `llms.txt` file listing the pages. It rejects page components whose
content cannot be included in those text copies.

## Build for GitHub Pages

```sh
NEXT_PUBLIC_BASE_PATH=/fair-offline-assessor npm run build
```

Omit `NEXT_PUBLIC_BASE_PATH` when serving the site at the domain root.
