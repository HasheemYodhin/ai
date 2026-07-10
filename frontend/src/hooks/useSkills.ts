import { useState, useCallback, useEffect } from 'react'
import { v4 as uuidv4 } from 'uuid'
import type { Skill } from '@/types'

const STORAGE_KEY = 'dabba-skills'

function loadSkills(): Skill[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveSkills(skills: Skill[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(skills))
  } catch {
    // localStorage full — silently fail, same convention as useHistory/useProjects
  }
}

export interface SkillInput {
  name: string
  description?: string
  instructions: string
}

interface UseSkillsReturn {
  skills: Skill[]
  createSkill: (input: SkillInput) => string
  deleteSkill: (id: string) => void
}

/**
 * Skills are reusable saved instructions — picking one from the "+" menu
 * applies it as a system-prompt override for that one message, actually
 * changing model behavior (not a cosmetic label like the other providers'
 * "custom GPT" marketing implies — this is the real mechanism underneath).
 */
export function useSkills(): UseSkillsReturn {
  const [skills, setSkills] = useState<Skill[]>(loadSkills)

  useEffect(() => {
    saveSkills(skills)
  }, [skills])

  const createSkill = useCallback((input: SkillInput): string => {
    const id = uuidv4()
    setSkills(prev => [{
      id,
      name: input.name.trim() || 'Untitled skill',
      description: input.description?.trim() || undefined,
      instructions: input.instructions.trim(),
      createdAt: Date.now(),
    }, ...prev])
    return id
  }, [])

  const deleteSkill = useCallback((id: string) => {
    setSkills(prev => prev.filter(s => s.id !== id))
  }, [])

  return { skills, createSkill, deleteSkill }
}
