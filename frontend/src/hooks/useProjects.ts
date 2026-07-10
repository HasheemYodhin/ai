import { useState, useCallback, useEffect } from 'react'
import { v4 as uuidv4 } from 'uuid'
import type { Project } from '@/types'

const STORAGE_KEY = 'dabba-projects'

export const PROJECT_COLORS = ['#c96442', '#2f9e5c', '#3b82f6', '#8b5cf6', '#eab308', '#ec4899', '#06b6d4', '#f97316']

function loadProjects(): Project[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveProjects(projects: Project[]) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(projects))
  } catch {
    // localStorage full — silently fail, same convention as useHistory
  }
}

export interface ProjectInput {
  name: string
  description?: string
  instructions?: string
  color?: string
}

interface UseProjectsReturn {
  projects: Project[]
  createProject: (input: ProjectInput) => string
  updateProject: (id: string, updates: Partial<ProjectInput>) => void
  deleteProject: (id: string) => void
}

/**
 * Projects are folders for grouping conversations, ChatGPT-Projects style:
 * each carries its own description + instructions (a system-prompt override
 * automatically applied to every conversation inside it — see App.tsx's
 * currentProject wiring). No server involvement, all local.
 */
export function useProjects(): UseProjectsReturn {
  const [projects, setProjects] = useState<Project[]>(loadProjects)

  useEffect(() => {
    saveProjects(projects)
  }, [projects])

  const createProject = useCallback((input: ProjectInput): string => {
    const id = uuidv4()
    const color = input.color ?? PROJECT_COLORS[Math.abs(hashCode(id)) % PROJECT_COLORS.length]
    setProjects(prev => [{
      id,
      name: input.name.trim() || 'Untitled project',
      description: input.description?.trim() || undefined,
      instructions: input.instructions?.trim() || undefined,
      color,
      createdAt: Date.now(),
    }, ...prev])
    return id
  }, [])

  const updateProject = useCallback((id: string, updates: Partial<ProjectInput>) => {
    setProjects(prev => prev.map(p => (p.id === id ? {
      ...p,
      ...(updates.name !== undefined ? { name: updates.name.trim() || p.name } : {}),
      ...(updates.description !== undefined ? { description: updates.description.trim() || undefined } : {}),
      ...(updates.instructions !== undefined ? { instructions: updates.instructions.trim() || undefined } : {}),
      ...(updates.color !== undefined ? { color: updates.color } : {}),
    } : p)))
  }, [])

  const deleteProject = useCallback((id: string) => {
    setProjects(prev => prev.filter(p => p.id !== id))
  }, [])

  return { projects, createProject, updateProject, deleteProject }
}

function hashCode(s: string): number {
  let h = 0
  for (let i = 0; i < s.length; i++) h = (h << 5) - h + s.charCodeAt(i) | 0
  return h
}
