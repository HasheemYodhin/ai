import { useState, useMemo } from 'react'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { X, Copy, Check, Code2, Eye } from 'lucide-react'
import { useArtifact, isPreviewable } from '@/hooks/useArtifact'
import { useTheme } from '@/hooks/useTheme'
import { DownloadMenu } from './DownloadMenu'
import { cn } from '@/lib/utils'

/** Slide-out panel for a sizeable code/doc block — see useArtifact for the trigger. */
export function ArtifactPanel() {
  const { artifact, closeArtifact } = useArtifact()
  const { theme } = useTheme()
  const [tab, setTab] = useState<'code' | 'preview'>('code')
  const [copied, setCopied] = useState(false)

  const previewable = artifact ? isPreviewable(artifact.language, artifact.code) : false

  // Reset to the code tab whenever a different artifact opens.
  const key = artifact ? `${artifact.title}:${artifact.code.length}` : ''
  useMemo(() => setTab('code'), [key])

  const handleCopy = async () => {
    if (!artifact) return
    await navigator.clipboard.writeText(artifact.code)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  return (
    <div className={cn(
      'flex flex-col h-full border-l border-border dark:border-border-dark bg-surface dark:bg-surface-dark-secondary overflow-hidden transition-[width] duration-200',
      artifact ? 'w-[440px]' : 'w-0'
    )}>
      {artifact && (
        <>
          <div className="flex items-center justify-between px-4 py-3 border-b border-border dark:border-border-dark flex-shrink-0">
            <div className="flex items-center gap-2 min-w-0">
              <span className="text-[9px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded bg-accent/10 text-accent flex-shrink-0">
                {artifact.language || 'text'}
              </span>
              <h3 className="text-xs font-semibold text-text-primary dark:text-text-dark-primary truncate">{artifact.title}</h3>
            </div>
            <button onClick={closeArtifact} className="p-1.5 rounded-lg hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary text-text-secondary flex-shrink-0">
              <X className="w-4 h-4" />
            </button>
          </div>

          {previewable && (
            <div className="flex items-center gap-1 px-3 pt-2 flex-shrink-0">
              <TabButton icon={Code2} label="Code" active={tab === 'code'} onClick={() => setTab('code')} />
              <TabButton icon={Eye} label="Preview" active={tab === 'preview'} onClick={() => setTab('preview')} />
            </div>
          )}

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
                  customStyle={{ margin: 0, minHeight: '100%', fontSize: '13px', lineHeight: '1.5' }}
                  showLineNumbers
                >
                  {artifact.code}
                </SyntaxHighlighter>
              </div>
            )}
          </div>

          <div className="flex items-center justify-end gap-1 px-3 py-2 border-t border-border dark:border-border-dark flex-shrink-0">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-medium text-text-secondary dark:text-text-dark-secondary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-green-500" /> : <Copy className="w-3.5 h-3.5" />}
              {copied ? 'Copied' : 'Copy'}
            </button>
            <DownloadMenu content={artifact.code} baseName={artifact.title} />
          </div>
        </>
      )}
    </div>
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
