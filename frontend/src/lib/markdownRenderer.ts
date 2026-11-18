/** Lazy loader for the markdown renderer chunk, shared so it can be warmed early. */
export const loadMarkdownRenderer = () =>
  import('@/components/MarkdownRenderer').then(mod => ({ default: mod.MarkdownRenderer }))

/** Warm the renderer chunk so the first streamed reply never shows raw markdown. */
export function preloadMarkdownRenderer(): void {
  void loadMarkdownRenderer()
}
