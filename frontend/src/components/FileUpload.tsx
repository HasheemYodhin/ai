import { useState, useRef, useCallback, type ChangeEvent, type DragEvent } from 'react'
import type { UploadedFile } from '@/types'
import { cn } from '@/lib/utils'
import { Upload, File as FileIcon, Image, X, FileText, AlertCircle } from 'lucide-react'

const ACCEPTED_TYPES = {
  'image/*': ['.png', '.jpg', '.jpeg', '.gif', '.webp', '.svg'],
  'text/*': ['.txt', '.md', '.json', '.csv', '.yaml', '.yml', '.xml'],
  'application/pdf': ['.pdf'],
  'application/json': ['.json'],
}

const MAX_FILE_SIZE = 10 * 1024 * 1024 // 10 MB
const MAX_FILES = 5

interface FileUploadProps {
  files: UploadedFile[]
  onFilesChange: (files: UploadedFile[]) => void
  disabled?: boolean
}

export function FileUpload({ files, onFilesChange, disabled = false }: FileUploadProps) {
  const [isDragOver, setIsDragOver] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  const processFiles = useCallback((fileList: FileList | File[]) => {
    setError(null)
    const newFiles: UploadedFile[] = []

    const remaining = MAX_FILES - files.length
    const toProcess = Array.from(fileList).slice(0, remaining)

    for (const file of toProcess) {
      if (file.size > MAX_FILE_SIZE) {
        setError(`"${file.name}" exceeds the 10 MB limit`)
        continue
      }

      const id = crypto.randomUUID()
      const uploaded: UploadedFile = {
        id,
        name: file.name,
        size: file.size,
        type: file.type,
      }

      if (file.type.startsWith('image/')) {
        const url = URL.createObjectURL(file)
        uploaded.preview = url
        uploaded.dataUrl = url
      } else {
        uploaded.dataUrl = URL.createObjectURL(file)
      }

      newFiles.push(uploaded)
    }

    if (toProcess.length < fileList.length) {
      setError(`Maximum ${MAX_FILES} files allowed`)
    }

    onFilesChange([...files, ...newFiles])
  }, [files, onFilesChange])

  const handleDrop = useCallback((e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(false)
    if (disabled) return
    if (e.dataTransfer.files.length > 0) {
      processFiles(e.dataTransfer.files)
    }
  }, [disabled, processFiles])

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault()
    setIsDragOver(true)
  }, [])

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false)
  }, [])

  const handleInputChange = useCallback((e: ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      processFiles(e.target.files)
    }
    e.target.value = ''
  }, [processFiles])

  const removeFile = useCallback((id: string) => {
    const file = files.find(f => f.id === id)
    if (file?.preview) URL.revokeObjectURL(file.preview)
    onFilesChange(files.filter(f => f.id !== id))
    setError(null)
  }, [files, onFilesChange])

  if (disabled) return null

  return (
    <div className="space-y-2">
      <div
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => inputRef.current?.click()}
        className={cn(
          'border-2 border-dashed rounded-xl p-6 text-center cursor-pointer transition-colors',
          isDragOver
            ? 'border-accent bg-accent/5'
            : 'border-border dark:border-border-dark hover:border-accent/50 hover:bg-accent/5'
        )}
      >
        <Upload className="w-8 h-8 mx-auto mb-2 text-text-tertiary dark:text-text-dark-tertiary" />
        <p className="text-sm text-text-secondary dark:text-text-dark-secondary">
          Drag & drop files here, or click to browse
        </p>
        <p className="text-xs text-text-tertiary dark:text-text-dark-tertiary mt-1">
          Images, text, PDF, JSON (max 10 MB each, up to 5 files)
        </p>
        <input
          ref={inputRef}
          type="file"
          multiple
          accept={Object.keys(ACCEPTED_TYPES).join(',')}
          onChange={handleInputChange}
          className="hidden"
        />
      </div>

      {error && (
        <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {files.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {files.map((file) => (
            <div
              key={file.id}
              className="flex items-center gap-2 px-3 py-2 rounded-lg bg-gray-100 dark:bg-gray-800 text-sm group"
            >
              {file.type.startsWith('image/') ? (
                <Image className="w-4 h-4 text-accent" />
              ) : (
                <FileText className="w-4 h-4 text-accent" />
              )}
              <span className="text-text-primary dark:text-text-dark-primary truncate max-w-[120px]">
                {file.name}
              </span>
              <button
                onClick={() => removeFile(file.id)}
                className="p-0.5 rounded hover:bg-gray-200 dark:hover:bg-gray-700 text-text-tertiary hover:text-red-500 transition-colors"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
