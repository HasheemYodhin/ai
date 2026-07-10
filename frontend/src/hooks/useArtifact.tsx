import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'

export interface ArtifactData {
  code: string
  language: string
  title: string
}

interface ArtifactContextType {
  artifact: ArtifactData | null
  openArtifact: (data: ArtifactData) => void
  closeArtifact: () => void
}

const ArtifactContext = createContext<ArtifactContextType>({
  artifact: null,
  openArtifact: () => {},
  closeArtifact: () => {},
})

/** Backs the artifact side panel — a slide-out view for sizeable code/doc blocks (see ArtifactPanel). */
export function ArtifactProvider({ children }: { children: ReactNode }) {
  const [artifact, setArtifact] = useState<ArtifactData | null>(null)

  const openArtifact = useCallback((data: ArtifactData) => setArtifact(data), [])
  const closeArtifact = useCallback(() => setArtifact(null), [])

  return (
    <ArtifactContext.Provider value={{ artifact, openArtifact, closeArtifact }}>
      {children}
    </ArtifactContext.Provider>
  )
}

export function useArtifact() {
  return useContext(ArtifactContext)
}

/** Languages/content we can render a live preview for. */
export function isPreviewable(language: string, code: string): boolean {
  const lang = language.toLowerCase()
  if (lang === 'html' || lang === 'svg' || lang === 'xml') return true
  return /^\s*<(!doctype|html|svg)/i.test(code)
}
