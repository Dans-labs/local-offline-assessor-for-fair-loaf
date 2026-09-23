# Documentation site

Requires Node.js 22+ and npm. Run from this directory:

```sh
npm ci
npm run dev
```

Edit pages in `src/app/**/page.mdx` and navigation in
`src/components/Navigation.tsx`. Use Markdown for content and follow
`src/app/reference/page.mdx` for side-by-side examples and parameter descriptions.
The build rejects MDX that the text exporter cannot preserve.

Build for GitHub Pages:

```sh
NEXT_PUBLIC_BASE_PATH=/fair-offline-assessor npm run build
```

The `out/` directory contains the site, each page's `index.md` and `llms.txt`.
Omit `NEXT_PUBLIC_BASE_PATH` when hosting at the domain root. Text exports are
generated during builds.

Run `npm test`, `npm run lint`, `npm run check` and `npm run format` before committing.
