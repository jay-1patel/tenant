import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { api, getToken, setToken, setUnauthorizedHandler } from './api'
import { navigate } from './router'
import type { AdminIdentity } from './types'

interface AuthState {
  loading: boolean
  /** The server has no admin accounts yet — the UI offers first-run setup. */
  needsSetup: boolean
  identity: AdminIdentity | null
  login: (username: string, password: string) => Promise<void>
  setup: (username: string, password: string, email?: string) => Promise<void>
  logout: () => void
  can: (permission: string) => boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [loading, setLoading] = useState(true)
  const [needsSetup, setNeedsSetup] = useState(false)
  const [identity, setIdentity] = useState<AdminIdentity | null>(null)

  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null)
      setIdentity(null)
    })
  }, [])

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const status = await api.get<{ has_admins: boolean }>('/api/auth/status')
        if (cancelled) return
        if (!status.has_admins) {
          setNeedsSetup(true)
          setLoading(false)
          return
        }
        if (!getToken()) {
          setLoading(false)
          return
        }
        const me = await api.get<AdminIdentity>('/api/auth/me')
        if (cancelled) return
        setIdentity(me)
      } catch {
        if (!cancelled) setIdentity(null)
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const login = useCallback(async (username: string, password: string) => {
    const res = await api.post<{ token: string; permissions: Record<string, boolean> }>(
      '/api/auth/login',
      { username, password },
      { anonymous: true },
    )
    setToken(res.token)
    const me = await api.get<AdminIdentity>('/api/auth/me')
    setIdentity(me)
    setNeedsSetup(false)
    // Tenant-scoped admins land straight in their own tenant; only super
    // admins start from the tenant list.
    if (me.role !== 'super_admin' && me.tenant_id) {
      navigate(`/tenants/${encodeURIComponent(me.tenant_id)}/overview`)
    }
  }, [])

  const setup = useCallback(async (username: string, password: string, email?: string) => {
    const res = await api.post<{ token: string }>('/api/auth/first-admin', {
      username,
      password,
      email: email || null,
    })
    setToken(res.token)
    const me = await api.get<AdminIdentity>('/api/auth/me')
    setIdentity(me)
    setNeedsSetup(false)
  }, [])

  const logout = useCallback(() => {
    setToken(null)
    setIdentity(null)
  }, [])

  const can = useCallback(
    (permission: string) => {
      if (!identity) return false
      // Only a super admin bypasses the switch list; admins and sub admins
      // are granted exactly what /api/auth/me reports (the stored set).
      if (identity.role === 'super_admin') return true
      return Boolean(identity.permissions?.[permission])
    },
    [identity],
  )

  const value = useMemo(
    () => ({ loading, needsSetup, identity, login, setup, logout, can }),
    [loading, needsSetup, identity, login, setup, logout, can],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used inside <AuthProvider>')
  return ctx
}
