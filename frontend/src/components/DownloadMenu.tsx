import { useState, useRef, useEffect } from 'react'
import { Download, FileText, FileType, FileSpreadsheet, Loader2, ChevronRight } from 'lucide-react'
import { cn } from '@/lib/utils'
import {
  TEXT_FORMATS,
  downloadText,
  downloadPdf,
  downloadDocx,
  downloadXlsx,
  type TextFormat,
} from '@/lib/download'

interface DownloadMenuProps {
  /** The content to export (assistant reply). */
  content: string
  /** Base name for the file (usually derived from the conversation/first line). */
  baseName: string
}

export function DownloadMenu({ content, baseName }: DownloadMenuProps) {
  const [open, setOpen] = useState(false)
  const [showText, setShowText] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function onClickOutside(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false)
        setShowText(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [])

  const run = async (key: string, fn: () => void | Promise<void>) => {
    try {
      setBusy(key)
      await fn()
    } catch (err) {
      console.error('Export failed:', err)
      alert(`Export failed: ${(err as Error).message}`)
    } finally {
      setBusy(null)
      setOpen(false)
      setShowText(false)
    }
  }

  const handleText = (fmt: TextFormat) => run(fmt.ext, () => downloadText(content, fmt, baseName))

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        title="Download"
        className="p-1 rounded-md text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
      >
        {busy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Download className="w-3 h-3" />}
      </button>

      {open && (
        <div className="absolute left-0 top-full mt-1 w-52 rounded-xl bg-surface dark:bg-surface-dark-secondary border border-border dark:border-border-dark shadow-lg z-40 py-1 animate-fade-in">
          <MenuItem icon={<FileType className="w-3.5 h-3.5 text-red-500" />} label="PDF (.pdf)" busy={busy === 'pdf'}
            onClick={() => run('pdf', () => downloadPdf(content, baseName))} />
          <MenuItem icon={<FileText className="w-3.5 h-3.5 text-blue-500" />} label="Word (.docx)" busy={busy === 'docx'}
            onClick={() => run('docx', () => downloadDocx(content, baseName))} />
          <MenuItem icon={<FileSpreadsheet className="w-3.5 h-3.5 text-green-600" />} label="Excel (.xlsx)" busy={busy === 'xlsx'}
            onClick={() => run('xlsx', () => downloadXlsx(content, baseName))} />

          <div className="my-1 border-t border-border dark:border-border-dark" />

          {/* Text formats submenu */}
          <button
            onClick={() => setShowText(s => !s)}
            className="w-full flex items-center justify-between gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
          >
            <span className="flex items-center gap-2 text-xs text-text-primary dark:text-text-dark-primary">
              <FileText className="w-3.5 h-3.5 text-text-tertiary" />
              Text / code…
            </span>
            <ChevronRight className={cn('w-3 h-3 text-text-tertiary transition-transform', showText && 'rotate-90')} />
          </button>

          {showText && (
            <div className="max-h-52 overflow-y-auto scrollbar-thin border-t border-border dark:border-border-dark">
              {TEXT_FORMATS.map(fmt => (
                <button
                  key={fmt.ext}
                  onClick={() => handleText(fmt)}
                  className="w-full flex items-center justify-between gap-2 px-3 py-1.5 pl-7 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
                >
                  <span className="text-xs text-text-primary dark:text-text-dark-primary">{fmt.label}</span>
                  <span className="text-[10px] font-mono text-text-tertiary">.{fmt.ext}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function MenuItem({ icon, label, busy, onClick }: { icon: React.ReactNode; label: string; busy: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2 px-3 py-1.5 text-left hover:bg-surface-tertiary dark:hover:bg-surface-dark-tertiary transition-colors"
    >
      {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin text-text-tertiary" /> : icon}
      <span className="text-xs text-text-primary dark:text-text-dark-primary">{label}</span>
    </button>
  )
}
