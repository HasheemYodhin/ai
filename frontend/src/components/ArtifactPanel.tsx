import { useState, useRef, useCallback, useEffect } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { X, Copy, Check, Code2, Eye, Maximize2, Minimize2, GripVertical, Globe, Loader2 } from 'lucide-react'
import { useArtifact, isPreviewable } from '@/hooks/useArtifact'
import { useTheme } from '@/hooks/useTheme'
import { DownloadMenu } from './DownloadMenu'
import { apiClient } from '@/api/client'
import { cn } from '@/lib/utils'

const MIN_WIDTH = 320
const MAX_WIDTH = 900
const DEFAULT_WIDTH = 440

/** Slide-out panel for a sizeable code/doc block — see useArtifact for the trigger. */
export function ArtifactPanel() {
  const { artifact, closeArtifact } = useArtifact()
  const { theme } = useTheme()
  const [tab, setTab] = useState<'code' | 'preview'>('code')
  const [copied, setCopied] = useState(false)
  const [expanded, setExpanded] = useState(false)
  const [panelWidth, setPanelWidth] = useState(DEFAULT_WIDTH)
  const [publishing, setPublishing] = useState(false)
  const [publishedUrl, setPublishedUrl] = useState<string | null>(null)
  const [publishError, setPublishError] = useState('')
  const isDragging = useRef(false)
  const dragStartX = useRef(0)
  const dragStartWidth = useRef(DEFAULT_WIDTH)

  const previewable = artifact ? isPreviewable(artifact.language, artifact.code) : false

  // Reset the publish state whenever a different artifact opens.
  useEffect(() => {
    setPublishedUrl(null)
    setPublishError('')
  }, [artifact?.title, artifact?.code])

  const handlePublish = async () => {
    if (!artifact || publishing) return
    setPublishing(true)
    setPublishError('')
    try {
      const ext = artifact.language.toLowerCase() === 'svg' ? 'svg' : 'html'
      const mediaType = ext === 'svg' ? 'image/svg+xml' : 'text/html'
      const result = await apiClient.publishArtifact(
        `${artifact.title || 'artifact'}.${ext}`, artifact.code, mediaType, artifact.title || 'Untitled artifact',
      )
      setPublishedUrl(result.url)
    } catch (err) {
      setPublishError((err as Error).message || 'Could not publish this artifact')
    } finally {
      setPublishing(false)
    }
  }

  // Select the appropriate initial tab whenever a different artifact opens.
  useEffect(() => {
    setTab(previewable ? 'preview' : 'code')
  }, [artifact, previewable])

  const handleCopy = async () => {
    if (!artifact) return
    await navigator.clipboard.writeText(artifact.code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  // Drag-to-resize logic
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    isDragging.current = true
    dragStartX.current = e.clientX
    dragStartWidth.current = panelWidth
    e.preventDefault()
  }, [panelWidth])

  useEffect(() => {
    const onMouseMove = (e: MouseEvent) => {
      if (!isDragging.current) return
      const delta = dragStartX.current - e.clientX
      const newWidth = Math.min(MAX_WIDTH, Math.max(MIN_WIDTH, dragStartWidth.current + delta))
      setPanelWidth(newWidth)
    }
    const onMouseUp = () => { isDragging.current = false }
    window.addEventListener('mousemove', onMouseMove)
    window.addEventListener('mouseup', onMouseUp)
    return () => {
      window.removeEventListener('mousemove', onMouseMove)
      window.removeEventListener('mouseup', onMouseUp)
    }
  }, [])

  // Close expanded mode on Escape
  useEffect(() => {
    if (!expanded) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setExpanded(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [expanded])

  const contentArea = (
    <div className="flex-1 overflow-hidden min-h-0">
      {tab === 'preview' && previewable ? (
        <iframe
          title={artifact?.title}
          srcDoc={artifact?.code}
          sandbox="allow-scripts"
          className="w-full h-full bg-white"
        />
      ) : (
        <div className="h-full overflow-auto scrollbar-thin">
          <SyntaxHighlighter
            language={artifact?.language || 'text'}
            style={theme === 'dark' ? oneDark : oneLight}
            customStyle={{ margin: 0, minHeight: '100%', fontSize: '13px', lineHeight: '1.5' }}
            showLineNumbers
          >
            {artifact?.code ?? ''}
          </SyntaxHighlighter>
        </div>
      )}
    </div>
  )

  const toolbar = (
    <div className="flex items-center justify-between px-4 py-3 border-b border-border dark:border-border-dark flex-shrink-0">
      <div className="flex items-center gap-2 min-w-0">
        <span className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-accent/10 text-accent flex-shrink-0">
          {artifact?.language || 'text'}
        </span>
        <h3 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary truncate">{artifact?.title}</h3>
      </div>
      <div className="flex items-center gap-1 flex-shrink-0">
        {/* Expand / Collapse */}
        <button
          onClick={() => setExpanded(v => !v)}
          title={expanded ? 'Exit fullscreen' : 'Expand to fullscreen'}
          className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
        >
          {expanded ? <Minimize2 className="w-4 h-4" /> : <Maximize2 className="w-4 h-4" />}
        </button>
        <button
          onClick={() => { setExpanded(false); closeArtifact() }}
          className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
    </div>
  )

  const tabs = previewable && (
    <div className="flex items-center gap-1 px-3 pt-2 flex-shrink-0">
      <TabButton icon={Code2} label="Code" active={tab === 'code'} onClick={() => setTab('code')} />
      <TabButton icon={Eye} label="Preview" active={tab === 'preview'} onClick={() => setTab('preview')} />
    </div>
  )

  const footer = (
    <div className="flex flex-col gap-2 border-t border-border dark:border-border-dark flex-shrink-0">
      <div className="flex items-center justify-end gap-1 px-3 py-2">
        <button
          onClick={handleCopy}
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
        >
          {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
        {previewable && (
          <button
            onClick={() => void handlePublish()}
            disabled={publishing}
            className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors disabled:opacity-50"
          >
            {publishing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Globe className="w-3.5 h-3.5" />}
            Publish
          </button>
        )}
        <DownloadMenu content={artifact?.code ?? ''} baseName={artifact?.title ?? 'snippet'} />
      </div>
      {(publishedUrl || publishError) && (
        <div className="px-3 pb-2">
          {publishedUrl ? (
            <div className="flex items-center gap-2 rounded-lg bg-accent/10 px-2.5 py-2 text-xs">
              <Globe className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
              <a href={publishedUrl} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-accent underline">{publishedUrl}</a>
              <button
                onClick={() => { void navigator.clipboard.writeText(publishedUrl) }}
                className="flex-shrink-0 text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"
              ><Copy className="h-3 w-3" /></button>
            </div>
          ) : (
            <p className="text-xs text-red-500">{publishError}</p>
          )}
        </div>
      )}
    </div>
  )

  return (
    <>
      {/* ── Fullscreen expanded overlay ────────────────────────────────────── */}
      {expanded && artifact && (
        <div className="fixed inset-0 z-50 flex flex-col bg-surface dark:bg-surface-dark animate-fade-in">
          {/* Header */}
          <div className="flex items-center justify-between px-6 py-4 border-b border-border dark:border-border-dark flex-shrink-0">
            <div className="flex items-center gap-3 min-w-0">
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded-md bg-accent/10 text-accent flex-shrink-0">
                {artifact.language || 'text'}
              </span>
              <h2 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary truncate">{artifact.title}</h2>
            </div>
            <div className="flex items-center gap-2 flex-shrink-0">
              {previewable && (
                <div className="flex items-center gap-1 mr-2 p-1 rounded-xl bg-surface-secondary dark:bg-surface-dark-tertiary border border-border dark:border-border-dark">
                  <TabButton icon={Code2} label="Code" active={tab === 'code'} onClick={() => setTab('code')} />
                  <TabButton icon={Eye} label="Preview" active={tab === 'preview'} onClick={() => setTab('preview')} />
                </div>
              )}
              <button
                onClick={handleCopy}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors border border-border dark:border-border-dark"
              >
                {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
                {copied ? 'Copied' : 'Copy'}
              </button>
              {previewable && (
                <button
                  onClick={() => void handlePublish()}
                  disabled={publishing}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors border border-border dark:border-border-dark disabled:opacity-50"
                >
                  {publishing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Globe className="w-3.5 h-3.5" />}
                  Publish
                </button>
              )}
              <DownloadMenu content={artifact.code} baseName={artifact.title} />
              <button
                onClick={() => setExpanded(false)}
                title="Exit fullscreen (Esc)"
                className="p-2 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary dark:text-text-dark-secondary transition-colors border border-border dark:border-border-dark"
              >
                <Minimize2 className="w-4 h-4" />
              </button>
              <button
                onClick={() => { setExpanded(false); closeArtifact() }}
                className="p-2 rounded-lg hover:bg-red-500/10 text-text-secondary hover:text-red-500 transition-colors border border-border dark:border-border-dark"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
          {(publishedUrl || publishError) && (
            <div className="border-b border-border px-6 py-2 dark:border-border-dark">
              {publishedUrl ? (
                <div className="flex items-center gap-2 text-xs">
                  <Globe className="h-3.5 w-3.5 flex-shrink-0 text-accent" />
                  <a href={publishedUrl} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-accent underline">{publishedUrl}</a>
                  <button
                    onClick={() => { void navigator.clipboard.writeText(publishedUrl) }}
                    className="flex-shrink-0 text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"
                  ><Copy className="h-3 w-3" /></button>
                </div>
              ) : (
                <p className="text-xs text-red-500">{publishError}</p>
              )}
            </div>
          )}

          {/* Content */}
          <div className="flex-1 overflow-hidden min-h-0">
            {tab === 'preview' && previewable ? (
              <iframe
                title={artifact.title}
                srcDoc={artifact.code}
                sandbox="allow-scripts"
                className="w-full h-full bg-white"
              />
            ) : (
              <div className="h-full overflow-auto scrollbar-thin">
                <SyntaxHighlighter
                  language={artifact.language || 'text'}
                  style={theme === 'dark' ? oneDark : oneLight}
                  customStyle={{ margin: 0, minHeight: '100%', fontSize: '14px', lineHeight: '1.6', borderRadius: 0 }}
                  showLineNumbers
                >
                  {artifact.code}
                </SyntaxHighlighter>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── Slide-out side panel ───────────────────────────────────────────── */}
      <div
        className={cn(
          'relative flex flex-col h-full border-l border-border dark:border-border-dark bg-surface dark:bg-surface-dark-secondary overflow-hidden transition-[width] duration-200',
          artifact ? '' : 'w-0'
        )}
        style={artifact ? { width: panelWidth } : undefined}
      >
        {/* Drag handle */}
        {artifact && (
          <div
            onMouseDown={onMouseDown}
            className="absolute left-0 top-0 h-full w-1.5 cursor-col-resize group z-10 flex items-center justify-center hover:bg-accent/20 transition-colors"
            title="Drag to resize"
          >
            <GripVertical className="w-3 h-3 text-text-tertiary opacity-0 group-hover:opacity-100 transition-opacity" />
          </div>
        )}

        {artifact && (
          <>
            {toolbar}
            {tabs}
            {contentArea}
            {footer}
          </>
        )}
      </div>
    </>
  )
}

function TabButton({ icon: Icon, label, active, onClick }: {
  icon: typeof Code2; label: string; active: boolean; onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors',
        active ? 'bg-accent/10 text-accent' : 'text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary'
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      {label}
    </button>
  )
}
