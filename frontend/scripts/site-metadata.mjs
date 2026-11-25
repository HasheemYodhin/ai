// Write robots.txt (plus sitemap.xml and absolute URLs when SITE_URL is set).
//
// Usage (run by `npm run build`): node scripts/site-metadata.mjs
// Optional env: SITE_URL=https://dabba.example.com  (no trailing slash)
//               DIST_DIR=path/to/built/client   (default: dist)
import { readFile, writeFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
// DIST_DIR lets a test build write somewhere other than the committed dist/.
const dist = process.env.DIST_DIR ? path.resolve(process.env.DIST_DIR) : path.join(root, 'dist')
const siteUrl = (process.env.SITE_URL || process.env.VITE_SITE_URL || '').replace(/\/+$/, '')

if (siteUrl) {
  const html = (await readFile(path.join(dist, 'index.html'), 'utf8'))
    .replace('</head>', `    <link rel="canonical" href="${siteUrl}/" />\n    <meta property="og:url" content="${siteUrl}/" />\n  </head>`)
    .replace('content="/og-image.png"', `content="${siteUrl}/og-image.png"`)
  await writeFile(path.join(dist, 'index.html'), html)
}

// Allow all crawlers, including AI search crawlers; keep private app routes out of the index.
const robots = [
  'User-agent: *',
  'Allow: /',
  'Disallow: /c/',
  'Disallow: /v1/',
  '',
  ...(siteUrl ? [`Sitemap: ${siteUrl}/sitemap.xml`, ''] : []),
].join('\n')
await writeFile(path.join(dist, 'robots.txt'), robots)

if (siteUrl) {
  const today = new Date().toISOString().slice(0, 10)
  const pages = ['/', '/try', '/signup', '/login', '/privacy', '/terms']
  const urls = pages.map(page => `  <url><loc>${siteUrl}${page}</loc><lastmod>${today}</lastmod></url>`).join('\n')
  await writeFile(path.join(dist, 'sitemap.xml'), `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls}\n</urlset>\n`)
}
