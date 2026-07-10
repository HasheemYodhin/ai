import { useMemo, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark, oneLight } from 'react-syntax-highlighter/dist/esm/styles/prism'
import remarkGfm from 'remark-gfm'
import type { Components } from 'react-markdown'
import { Copy, Check, ChevronDown, ChevronRight, Maximize2, FileCode2, Play, Loader2, TerminalSquare, X } from 'lucide-react'
import { useTheme } from '@/hooks/useTheme'
import { useArtifact, isPreviewable } from '@/hooks/useArtifact'
import { cn } from '@/lib/utils'
import { apiClient } from '@/api/client'

// Blocks at or above this size open as a compact artifact card (see
// ArtifactPanel) instead of rendering the full code inline — keeps long
// generated files from dominating the chat while still being one click away.
const ARTIFACT_LINE_THRESHOLD = 15

function guessTitle(language: string, code: string): string {
  const firstLine = code.split('\n', 1)[0]?.trim() ?? ''
  const commentMatch = /^(?:#|\/\/|<!--)\s*(.+?)\s*(?:-->)?$/.exec(firstLine)
  if (commentMatch && commentMatch[1].length < 60) return commentMatch[1]
  return `${language || 'code'} snippet`
}

interface MarkdownRendererProps {
  content: string
  className?: string
}

export function MarkdownRenderer({ content, className }: MarkdownRendererProps) {
  const { theme } = useTheme()
  const isDark = theme === 'dark'

  const components: Components = useMemo(() => ({
    code({ className: langClassName, children, ...props }) {
      const match = /language-(\w+)/.exec(langClassName ?? '')
      const language = match ? match[1] : ''
      const codeString = String(children).replace(/\n$/, '')

      if (match) {
        return <CodeBlock language={language} code={codeString} isDark={isDark} />
      }

      return (
        <code
          className="bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded text-sm font-mono text-accent dark:text-accent-dark-hover"
          {...props}
        >
          {children}
        </code>
      )
    },
    pre({ children }) {
      return <>{children}</>
    },
    table({ children }) {
      return (
        <div className="overflow-x-auto my-4">
          <table className="min-w-full border-collapse border border-border dark:border-border-dark">
            {children}
          </table>
        </div>
      )
    },
    th({ children }) {
      return (
        <th className="border border-border dark:border-border-dark bg-gray-50 dark:bg-gray-800 px-3 py-2 text-left text-sm font-semibold">
          {children}
        </th>
      )
    },
    td({ children }) {
      return (
        <td className="border border-border dark:border-border-dark px-3 py-2 text-sm">
          {children}
        </td>
      )
    },
    a({ href, children }) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noopener noreferrer"
          className="text-accent hover:text-accent-hover underline underline-offset-2"
        >
          {children}
        </a>
      )
    },
    img({ src, alt }) {
      return (
        <img
          src={src}
          alt={alt ?? ''}
          className="max-w-full rounded-lg my-4"
          loading="lazy"
        />
      )
    },
    ul({ children }) {
      return <ul className="list-disc list-inside space-y-1 my-2">{children}</ul>
    },
    ol({ children }) {
      return <ol className="list-decimal list-inside space-y-1 my-2">{children}</ol>
    },
    li({ children }) {
      return <li className="text-[15px] leading-relaxed">{children}</li>
    },
    p({ children }) {
      return <p className="text-[15px] leading-relaxed mb-2 last:mb-0">{children}</p>
    },
    h1({ children }) {
      return <h1 className="text-xl font-bold mt-6 mb-3">{children}</h1>
    },
    h2({ children }) {
      return <h2 className="text-lg font-bold mt-5 mb-2">{children}</h2>
    },
    h3({ children }) {
      return <h3 className="text-base font-semibold mt-4 mb-2">{children}</h3>
    },
    blockquote({ children }) {
      return (
        <blockquote className="border-l-4 border-accent pl-4 my-2 italic text-text-secondary dark:text-text-dark-secondary">
          {children}
        </blockquote>
      )
    },
    hr() {
      return <hr className="my-4 border-border dark:border-border-dark" />
    },
  }), [isDark])

  return (
    <div className={cn('prose prose-sm max-w-none dark:prose-invert', className)}>
      <ReactMarkdown
        components={components}
        remarkPlugins={[remarkGfm]}
      >
        {content}
      </ReactMarkdown>
    </div>
  )
}

function CodeBlock({ language, code, isDark }: { language: string; code: string; isDark: boolean }) {
  const [copied, setCopied] = useState(false)
  const [collapsed, setCollapsed] = useState(false)
  const [running, setRunning] = useState(false)
  const [stdinOpen, setStdinOpen] = useState(false)
  const [stdin, setStdin] = useState('')
  const [result, setResult] = useState<{ exitCode: number | null; stdout: string; stderr: string; timedOut: boolean; truncated?: boolean; durationMs: number; phase?: string } | null>(null)
  const [runError, setRunError] = useState('')
  const { openArtifact } = useArtifact()

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      // fallback copy not available
    }
  }, [code])

  const lineCount = useMemo(() => code.split('\n').length, [code])
  const title = useMemo(() => guessTitle(language, code), [language, code])
  const handleOpenArtifact = useCallback(() => {
    openArtifact({ code, language, title })
  }, [openArtifact, code, language, title])

  const handleRun = useCallback(async () => {
    setRunning(true)
    setRunError('')
    setResult(null)
    try {
      setResult(await apiClient.executeCode(language, code, stdin))
    } catch (error) {
      setRunError(error instanceof Error ? error.message : 'Execution failed')
    } finally {
      setRunning(false)
    }
  }, [language, code, stdin])

  const runner = (
    <>
      <button
        onClick={handleRun}
        disabled={running || !language}
        title={language ? `Run ${language}` : 'Add a language to this code fence to run it'}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium bg-green-600 hover:bg-green-700 disabled:opacity-40 text-white transition-colors"
      >
        {running ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {running ? 'Running' : 'Run'}
      </button>
      <button
        onClick={() => setStdinOpen(v => !v)}
        title="Provide standard input"
        className="flex items-center gap-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
      >
        <TerminalSquare className="w-3.5 h-3.5" /> Input
      </button>
    </>
  )

  const executionPanel = (stdinOpen || result || runError) && (
    <div className="border-t border-border dark:border-border-dark bg-gray-950 text-gray-100">
      {stdinOpen && (
        <div className="p-3 border-b border-gray-800">
          <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-1.5">Standard input</label>
          <textarea
            value={stdin}
            onChange={e => setStdin(e.target.value)}
            placeholder="Input passed to the program…"
            rows={3}
            className="w-full resize-y rounded border border-gray-700 bg-gray-900 px-2.5 py-2 font-mono text-xs outline-none focus:border-green-500"
          />
        </div>
      )}
      {(result || runError) && (
        <div className="relative p-3 font-mono text-xs">
          <button onClick={() => { setResult(null); setRunError('') }} className="absolute right-2 top-2 p-1 text-gray-500 hover:text-gray-200" title="Close output"><X className="w-3.5 h-3.5" /></button>
          <div className="flex items-center gap-2 mb-2 pr-6 font-sans text-[10px]">
            <span className={cn('font-semibold', runError || result?.exitCode !== 0 ? 'text-red-400' : 'text-green-400')}>
              {runError ? 'Execution error' : result?.timedOut ? 'Timed out' : result?.phase === 'compile' ? 'Compilation failed' : `Exited ${result?.exitCode}`}
            </span>
            {result && <span className="text-gray-500">{result.durationMs} ms</span>}
            {result?.truncated && <span className="text-amber-400">output truncated</span>}
          </div>
          {runError && <pre className="whitespace-pre-wrap text-red-300">{runError}</pre>}
          {result?.stdout && <pre className="whitespace-pre-wrap break-words text-gray-100">{result.stdout}</pre>}
          {result?.stderr && <pre className="mt-2 whitespace-pre-wrap break-words text-red-300">{result.stderr}</pre>}
          {result && !result.stdout && !result.stderr && <span className="text-gray-500">Program finished without output.</span>}
        </div>
      )}
    </div>
  )

  // Large blocks collapse into a compact artifact card — full content is one
  // click away in the side panel (with a live preview for HTML/SVG) instead
  // of dominating the chat transcript.
  if (lineCount >= ARTIFACT_LINE_THRESHOLD) {
    return (
      <div className="my-4 rounded-lg overflow-hidden border border-border dark:border-border-dark bg-surface-secondary dark:bg-surface-dark-tertiary">
        <div className="flex items-center gap-3 p-3.5">
        <button onClick={handleOpenArtifact} className="contents text-left group">
          <div className="w-9 h-9 rounded-lg bg-accent/10 flex items-center justify-center flex-shrink-0">
          <FileCode2 className="w-4.5 h-4.5 text-accent" />
          </div>
          <div className="flex-1 min-w-0 text-left">
          <p className="text-sm font-medium text-text-primary dark:text-text-dark-primary truncate">{title}</p>
          <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary">
            {language || 'text'} · {lineCount} lines
            {isPreviewable(language, code) && ' · preview available'}
          </p>
          </div>
          <span className="flex items-center gap-1 text-xs font-medium text-accent flex-shrink-0">
          <Maximize2 className="w-3.5 h-3.5" /> Open
          </span>
        </button>
        <div className="flex items-center gap-2">{runner}</div>
        </div>
        {executionPanel}
      </div>
    )
  }

  return (
    <div className="my-4 rounded-lg overflow-hidden border border-border dark:border-border-dark">
      <div className="flex items-center justify-between px-4 py-2 bg-gray-50 dark:bg-gray-800/50 border-b border-border dark:border-border-dark">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setCollapsed(!collapsed)}
            className="p-0.5 hover:bg-gray-200 dark:hover:bg-gray-700 rounded"
          >
            {collapsed ? (
              <ChevronRight className="w-3.5 h-3.5 text-text-secondary" />
            ) : (
              <ChevronDown className="w-3.5 h-3.5 text-text-secondary" />
            )}
          </button>
          <span className="text-xs font-medium text-text-secondary uppercase">
            {language}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {runner}
          <button
            onClick={handleOpenArtifact}
            title="Open in side panel"
            className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={handleCopy}
            className="flex items-center gap-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
          >
            {copied ? (
              <Check className="w-3.5 h-3.5 text-green-500" />
            ) : (
              <Copy className="w-3.5 h-3.5" />
            )}
            {copied ? 'Copied!' : 'Copy'}
          </button>
        </div>
      </div>
      {!collapsed && (
        <SyntaxHighlighter
          language={language}
          style={isDark ? oneDark : oneLight}
          customStyle={{
            margin: 0,
            borderRadius: 0,
            fontSize: '13px',
            lineHeight: '1.5',
          }}
          showLineNumbers
        >
          {code}
        </SyntaxHighlighter>
      )}
      {executionPanel}
    </div>
  )
}
