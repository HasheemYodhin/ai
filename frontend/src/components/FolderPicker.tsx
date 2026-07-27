import { useCallback, useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Folder, FolderCheck, FolderSearch, HardDrive, Loader2, RefreshCw, X } from 'lucide-react'
import { apiClient } from '@/api/client'
import type { DirectoryListing } from '@/types'

interface FolderPickerProps {
  isOpen: boolean
  value: string
  onClose: () => void
  onSelect: (path: string) => void
}

export function FolderPicker({ isOpen, value, onClose, onSelect }: FolderPickerProps) {
  const [listing, setListing] = useState<DirectoryListing | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [manualPath, setManualPath] = useState(value)
  const [nativePicking, setNativePicking] = useState(false)

  const browse = useCallback(async (path?: string) => {
    setLoading(true); setError('')
    try {
      const next = await apiClient.browseWorkspaceDirectories(path)
      setListing(next)
      if (next.path) setManualPath(next.path)
    }
    catch (err) { setError((err as Error).message) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => {
    if (isOpen) {
      setManualPath(value)
      void browse(value || undefined)
    }
  }, [browse, isOpen, value])

  const selectFolder = (path: string) => {
    onSelect(path)
    onClose()
  }

  const chooseFromComputer = async () => {
    setNativePicking(true); setError('')
    try {
      const result = await apiClient.pickWorkspaceDirectory((listing?.path ?? value) || undefined)
      if (result.path && !result.cancelled) selectFolder(result.path)
    } catch (err) { setError((err as Error).message) }
    finally { setNativePicking(false) }
  }

  if (!isOpen) return null
  const entries = listing?.path ? listing.directories : listing?.roots ?? []

  return <div className="fixed inset-0 z-[70] flex items-center justify-center bg-black/45 p-4" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <div className="flex max-h-[70vh] w-full max-w-xl flex-col overflow-hidden rounded-2xl border border-border bg-surface shadow-2xl dark:border-border-dark dark:bg-surface-dark">
      <header className="flex items-center gap-3 border-b border-border p-4 dark:border-border-dark">
        <FolderCheck className="h-5 w-5 text-accent" />
        <div className="min-w-0 flex-1"><h2 className="text-sm font-semibold text-text-primary dark:text-text-dark-primary">Choose Cowork folder</h2><p className="mt-0.5 truncate text-[10px] text-text-tertiary">{listing?.path || 'Available locations'}</p></div>
        <button onClick={onClose} className="p-1 text-text-tertiary hover:text-text-primary dark:hover:text-text-dark-primary"><X className="h-4 w-4" /></button>
      </header>
      <div className="border-b border-border px-4 py-3 dark:border-border-dark">
        <button onClick={() => void chooseFromComputer()} disabled={nativePicking} className="flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-3 py-2.5 text-xs font-semibold text-white hover:bg-accent-hover disabled:cursor-wait disabled:opacity-60">{nativePicking ? <Loader2 className="h-4 w-4 animate-spin" /> : <FolderSearch className="h-4 w-4" />}{nativePicking ? 'Waiting for folder selection…' : 'Browse folders on this computer'}</button>
        <p className="mt-1.5 text-center text-[9px] text-text-tertiary">Opens your computer’s folder-selection window.</p>
      </div>
      <form onSubmit={event => { event.preventDefault(); void browse(manualPath.trim() || undefined) }} className="flex gap-2 border-b border-border px-4 py-3 dark:border-border-dark">
        <input value={manualPath} onChange={event => setManualPath(event.target.value)} placeholder="Enter an exact folder path" className="glass-input min-w-0 flex-1 rounded-lg px-3 py-2 text-xs text-text-primary outline-none dark:text-text-dark-primary" />
        <button disabled={loading} type="submit" className="rounded-lg border border-border px-3 py-2 text-xs font-semibold text-text-secondary hover:border-accent hover:text-accent disabled:cursor-wait disabled:opacity-50 dark:border-border-dark dark:text-text-dark-secondary">{loading ? 'Loading…' : 'Open path'}</button>
      </form>
      <div className="flex items-center gap-2 border-b border-border px-4 py-2 dark:border-border-dark">
        <button disabled={!listing?.parent} onClick={() => void browse(listing?.parent ?? undefined)} className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs text-text-secondary hover:bg-surface-secondary disabled:opacity-30 dark:text-text-dark-secondary dark:hover:bg-surface-dark-secondary"><ChevronLeft className="h-3.5 w-3.5" /> Back</button>
        {listing?.path && <button onClick={() => selectFolder(listing.path!)} className="ml-auto flex items-center gap-1.5 rounded-lg bg-accent px-3 py-1.5 text-xs font-semibold text-white"><FolderCheck className="h-3.5 w-3.5" /> Select current folder</button>}
      </div>
      <div className="min-h-48 flex-1 overflow-y-auto p-3 scrollbar-thin">
        {loading ? <div className="flex h-40 items-center justify-center text-text-tertiary"><Loader2 className="h-5 w-5 animate-spin" /></div> : <div className="space-y-1">
          {entries.map(entry => <div key={entry.path} className="flex items-center gap-2 rounded-lg px-2 py-1.5 hover:bg-surface-secondary dark:hover:bg-surface-dark-secondary"><button onClick={() => void browse(entry.path)} className="flex min-w-0 flex-1 items-center gap-3 text-left"><span className="rounded-lg bg-accent/10 p-2 text-accent">{listing?.path ? <Folder className="h-4 w-4" /> : <HardDrive className="h-4 w-4" />}</span><span className="min-w-0 flex-1"><span className="block truncate text-xs font-semibold text-text-primary dark:text-text-dark-primary">{entry.name}</span><span className="block truncate text-[10px] text-text-tertiary">{entry.path}</span></span><ChevronRight className="h-4 w-4 flex-shrink-0 text-text-tertiary" /></button><button onClick={() => selectFolder(entry.path)} className="flex flex-shrink-0 items-center gap-1 rounded-md border border-border px-2 py-1.5 text-[10px] font-semibold text-text-secondary hover:border-accent hover:text-accent dark:border-border-dark dark:text-text-dark-secondary"><FolderCheck className="h-3 w-3" /> Select</button></div>)}
          {!entries.length && !error && <p className="py-12 text-center text-xs text-text-tertiary">This folder has no subfolders. You can select the current folder above.</p>}
        </div>}
        {error && <div className="flex items-center gap-3 rounded-lg bg-red-500/10 p-3 text-xs text-red-500"><span className="flex-1">{error}</span><button onClick={() => void browse((listing?.path ?? value) || undefined)} className="flex items-center gap-1 rounded-md bg-red-500/10 px-2 py-1 font-semibold hover:bg-red-500/20"><RefreshCw className="h-3 w-3" /> Retry</button></div>}
      </div>
    </div>
  </div>
}
