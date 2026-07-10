import { useState, useCallback } from 'react'
import { cn } from '@/lib/utils'
import { X, Maximize2, Minimize2, Loader2, ImageOff } from 'lucide-react'

interface ImagePreviewProps {
  src: string
  alt?: string
  className?: string
}

export function ImagePreview({ src, alt, className }: ImagePreviewProps) {
  const [expanded, setExpanded] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const [error, setError] = useState(false)

  const handleToggle = useCallback(() => {
    setExpanded(prev => !prev)
  }, [])

  return (
    <>
      <div className={cn('relative group inline-block', className)}>
        {!loaded && !error && (
          <div className="flex items-center justify-center w-48 h-32 rounded-lg bg-gray-100 dark:bg-gray-800 animate-pulse">
            <Loader2 className="w-6 h-6 text-text-tertiary animate-spin" />
          </div>
        )}

        {error && (
          <div className="flex flex-col items-center justify-center w-48 h-32 rounded-lg bg-gray-100 dark:bg-gray-800">
            <ImageOff className="w-6 h-6 text-text-tertiary mb-1" />
            <span className="text-xs text-text-tertiary">Failed to load</span>
          </div>
        )}

        <img
          src={src}
          alt={alt ?? ''}
          onLoad={() => setLoaded(true)}
          onError={() => { setLoaded(true); setError(true) }}
          className={cn(
            'max-w-full rounded-lg cursor-pointer transition-all',
            'hover:ring-2 hover:ring-accent',
            loaded ? 'block' : 'hidden',
            className
          )}
          style={{ maxHeight: expanded ? '600px' : '300px' }}
          onClick={handleToggle}
        />

        {loaded && !error && (
          <button
            onClick={handleToggle}
            className="absolute top-2 right-2 p-1.5 rounded-lg bg-black/50 text-white opacity-0 group-hover:opacity-100 transition-opacity hover:bg-black/70"
          >
            {expanded ? (
              <Minimize2 className="w-4 h-4" />
            ) : (
              <Maximize2 className="w-4 h-4" />
            )}
          </button>
        )}
      </div>

      {expanded && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-sm"
          onClick={() => setExpanded(false)}
        >
          <button
            onClick={() => setExpanded(false)}
            className="absolute top-4 right-4 p-2 rounded-full bg-black/50 text-white hover:bg-black/70 transition-colors"
          >
            <X className="w-6 h-6" />
          </button>
          <img
            src={src}
            alt={alt ?? ''}
            className="max-h-[90vh] max-w-[90vw] object-contain rounded-lg"
            onClick={e => e.stopPropagation()}
          />
          {alt && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 px-4 py-2 rounded-lg bg-black/50 text-white text-sm">
              {alt}
            </div>
          )}
        </div>
      )}
    </>
  )
}
