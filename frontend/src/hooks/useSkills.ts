import { useState, useCallback, useEffect } from 'react'
import { apiClient } from '@/api/client'
import type { Skill } from '@/types'

export interface SkillInput {
  name: string
  description?: string
  instructions: string
  script?: string
}

interface UseSkillsReturn {
  skills: Skill[]
  createSkill: (input: SkillInput) => Promise<string>
  deleteSkill: (id: string) => Promise<void>
}

/**
 * Skills are reusable saved instructions — picking one from the "+" menu
 * applies it as a system-prompt override for that one message, actually
 * changing model behavior (not a cosmetic label like the other providers'
 * "custom GPT" marketing implies — this is the real mechanism underneath).
 *
 * Server-persisted (via /v1/platform/skills), not localStorage — so skills
 * survive across devices/browsers and can be auto-matched server-side
 * (apiClient.matchSkill) instead of only being reachable through manual
 * "+" menu selection.
 */
export function useSkills(): UseSkillsReturn {
  const [skills, setSkills] = useState<Skill[]>([])

  const refresh = useCallback(async () => {
    try { setSkills(await apiClient.listSkills()) }
    catch { /* best-effort — the "+" menu just shows no skills until this succeeds */ }
  }, [])
  useEffect(() => { void refresh() }, [refresh])

  const createSkill = useCallback(async (input: SkillInput): Promise<string> => {
    const created = await apiClient.createSkillPackage({
      name: input.name.trim() || 'Untitled skill',
      instructions: input.instructions.trim(),
      description: input.description?.trim() || undefined,
      script: input.script?.trim() || undefined,
    })
    setSkills(prev => [created, ...prev])
    return created.id
  }, [])

  const deleteSkill = useCallback(async (id: string) => {
    setSkills(prev => prev.filter(s => s.id !== id))
    await apiClient.deleteSkillPackage(id).catch(() => void refresh())
  }, [refresh])

  return { skills, createSkill, deleteSkill }
}
