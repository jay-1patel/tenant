/**
 * Single fetch wrapper for the whole app.
 *
 * The admin JWT is kept in localStorage and attached as a bearer token. Every
 * non-2xx response is normalised into an `ApiError` carrying the server's
 * `detail`, so screens can surface backend validation text (publish failures,
 * permission refusals) instead of a generic "something went wrong".
 */

const TOKEN_KEY = 'tenant-console.token'
const TENANT_KEY = 'tenant-console.tenant'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY)
  } catch {
    return null
  }
}

export function setToken(token: string | null) {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token)
    else localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* private mode — the session simply does not persist */
  }
}

export function getActiveTenantId(): string | null {
  try {
    return localStorage.getItem(TENANT_KEY)
  } catch {
    return null
  }
}

export function setActiveTenantId(tenantId: string | null) {
  try {
    if (tenantId) localStorage.setItem(TENANT_KEY, tenantId)
    else localStorage.removeItem(TENANT_KEY)
  } catch {
    /* ignore */
  }
}

type Unauthorized = () => void

let onUnauthorized: Unauthorized = () => {}

export function setUnauthorizedHandler(fn: Unauthorized) {
  onUnauthorized = fn
}

async function readDetail(res: Response): Promise<string> {
  try {
    const body = await res.json()
    const detail = body?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length) {
      // pydantic validation errors
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) =>
          `${(d.loc ?? []).slice(1).join('.')}: ${d.msg ?? 'invalid'}`,
        )
        .join('; ')
    }
    if (detail) return JSON.stringify(detail)
    return body?.error || res.statusText || `Request failed (${res.status})`
  } catch {
    return res.statusText || `Request failed (${res.status})`
  }
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
  /** Skip the bearer token (used by the login and bootstrap calls). */
  anonymous?: boolean
}

export async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = 'GET', body, signal, anonymous } = options
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (body !== undefined) headers['Content-Type'] = 'application/json'

  if (!anonymous) {
    const token = getToken()
    if (token) headers.Authorization = `Bearer ${token}`
  }

  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    })
  } catch (err) {
    if ((err as Error)?.name === 'AbortError') throw err
    throw new ApiError(0, 'Cannot reach the backend. Is it running on port 9000?')
  }

  if (res.status === 401) {
    if (!anonymous) onUnauthorized()
    throw new ApiError(401, await readDetail(res))
  }
  if (!res.ok) {
    throw new ApiError(res.status, await readDetail(res))
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  return (text ? JSON.parse(text) : undefined) as T
}

export const api = {
  get: <T,>(path: string, signal?: AbortSignal) => request<T>(path, { signal }),
  post: <T,>(path: string, body?: unknown, options: RequestOptions = {}) =>
    request<T>(path, { ...options, method: 'POST', body }),
  put: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'PUT', body }),
  patch: <T,>(path: string, body?: unknown) => request<T>(path, { method: 'PATCH', body }),
  del: <T,>(path: string) => request<T>(path, { method: 'DELETE' }),
}
