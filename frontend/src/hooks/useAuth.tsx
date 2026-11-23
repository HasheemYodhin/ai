import { createContext, useContext, useState, useCallback, useEffect, type ReactNode } from 'react'
import { apiClient, type PlatformUser } from '@/api/client'

export interface UserProfile {
  id: string
  name: string
  email: string
  avatarColor: string
  createdAt: number
  role: string
}

const AVATAR_COLORS = ['#c96442', '#2f9e5c', '#3b82f6', '#8b5cf6', '#eab308', '#ec4899']

function toProfile(user: PlatformUser): UserProfile {
  const colorIndex = [...user.id].reduce((total, char) => total + char.charCodeAt(0), 0) % AVATAR_COLORS.length
  return { ...user, avatarColor: AVATAR_COLORS[colorIndex] }
}

interface AuthContextType {
  currentUser: UserProfile | null
  /** True when the server granted this account the admin role. Admin-only
   *  endpoints (code execution, Cowork, MCP, hooks, schedules, background
   *  processes) return 403 for everyone else, so the UI hides or disables them. */
  isAdmin: boolean
  isReady: boolean
  signup: (name: string, email: string, password: string) => Promise<void>
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  currentUser: null,
  isAdmin: false,
  isReady: false,
  signup: async () => {},
  login: async () => {},
  logout: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(null)
  const [isReady, setReady] = useState(false)

  useEffect(() => {
    const controller = new AbortController()
    apiClient.currentUser(controller.signal)
      .then(user => setCurrentUser(user ? toProfile(user) : null))
      .catch(() => setCurrentUser(null))
      .finally(() => setReady(true))
    return () => controller.abort()
  }, [])

  const signup = useCallback(async (name: string, email: string, password: string) => {
    if (!name.trim()) throw new Error('Name is required')
    if (!email.trim()) throw new Error('Email is required')
    if (password.length < 10) throw new Error('Password must be at least 10 characters')
    const { user } = await apiClient.signup(name.trim(), email.trim(), password)
    setCurrentUser(toProfile(user))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const { user } = await apiClient.login(email.trim(), password)
    setCurrentUser(toProfile(user))
  }, [])

  const logout = useCallback(() => {
    void apiClient.logout()
    setCurrentUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ currentUser, isAdmin: currentUser?.role === 'admin', isReady, signup, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
