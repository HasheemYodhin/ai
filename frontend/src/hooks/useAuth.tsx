import { createContext, useContext, useState, useCallback, type ReactNode } from 'react'
import { v4 as uuidv4 } from 'uuid'

const USERS_KEY = 'dabba-users'
const CURRENT_USER_KEY = 'dabba-current-user-id'

export interface UserProfile {
  id: string
  name: string
  email: string
  avatarColor: string
  createdAt: number
}

interface StoredUser extends UserProfile {
  passwordHash: string
}

const AVATAR_COLORS = ['#c96442', '#2f9e5c', '#3b82f6', '#8b5cf6', '#eab308', '#ec4899']

/**
 * Local-only auth: profiles + password hashes live in this browser's
 * localStorage, never sent anywhere. This is account-switching / a personal
 * profile, NOT real security — anyone with access to this browser profile
 * can read localStorage directly. Good enough for a single-user personal
 * app; do not reuse this pattern for anything multi-tenant or sensitive.
 */
async function hashPassword(password: string): Promise<string> {
  const data = new TextEncoder().encode(password)
  const digest = await crypto.subtle.digest('SHA-256', data)
  return Array.from(new Uint8Array(digest)).map(b => b.toString(16).padStart(2, '0')).join('')
}

function loadUsers(): StoredUser[] {
  try {
    const raw = localStorage.getItem(USERS_KEY)
    return raw ? JSON.parse(raw) : []
  } catch {
    return []
  }
}

function saveUsers(users: StoredUser[]) {
  try {
    localStorage.setItem(USERS_KEY, JSON.stringify(users))
  } catch {
    // localStorage full — silently fail, same convention as the other hooks
  }
}

function stripPassword(u: StoredUser): UserProfile {
  const { passwordHash, ...profile } = u
  void passwordHash
  return profile
}

interface AuthContextType {
  currentUser: UserProfile | null
  isReady: boolean
  signup: (name: string, email: string, password: string) => Promise<void>
  login: (email: string, password: string) => Promise<void>
  logout: () => void
}

const AuthContext = createContext<AuthContextType>({
  currentUser: null,
  isReady: false,
  signup: async () => {},
  login: async () => {},
  logout: () => {},
})

export function AuthProvider({ children }: { children: ReactNode }) {
  const [currentUser, setCurrentUser] = useState<UserProfile | null>(() => {
    const id = localStorage.getItem(CURRENT_USER_KEY)
    if (!id) return null
    const found = loadUsers().find(u => u.id === id)
    return found ? stripPassword(found) : null
  })

  const signup = useCallback(async (name: string, email: string, password: string) => {
    const trimmedEmail = email.trim().toLowerCase()
    if (!name.trim()) throw new Error('Name is required')
    if (!trimmedEmail) throw new Error('Email is required')
    if (password.length < 6) throw new Error('Password must be at least 6 characters')

    const users = loadUsers()
    if (users.some(u => u.email.toLowerCase() === trimmedEmail)) {
      throw new Error('An account with this email already exists')
    }

    const id = uuidv4()
    const passwordHash = await hashPassword(password)
    const user: StoredUser = {
      id,
      name: name.trim(),
      email: trimmedEmail,
      passwordHash,
      avatarColor: AVATAR_COLORS[Math.floor(Math.random() * AVATAR_COLORS.length)],
      createdAt: Date.now(),
    }
    saveUsers([...users, user])
    localStorage.setItem(CURRENT_USER_KEY, id)
    setCurrentUser(stripPassword(user))
  }, [])

  const login = useCallback(async (email: string, password: string) => {
    const trimmedEmail = email.trim().toLowerCase()
    const users = loadUsers()
    const user = users.find(u => u.email.toLowerCase() === trimmedEmail)
    if (!user) throw new Error('No account found with this email')

    const passwordHash = await hashPassword(password)
    if (passwordHash !== user.passwordHash) throw new Error('Incorrect password')

    localStorage.setItem(CURRENT_USER_KEY, user.id)
    setCurrentUser(stripPassword(user))
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem(CURRENT_USER_KEY)
    setCurrentUser(null)
  }, [])

  return (
    <AuthContext.Provider value={{ currentUser, isReady: true, signup, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
