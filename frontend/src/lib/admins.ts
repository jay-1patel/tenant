import { api } from './api'
import type { AdminIdentity } from './types'

export interface AdminRecord {
  username: string
  email: string | null
  role: 'super_admin' | 'admin' | 'sub_admin'
  permissions: Record<string, boolean>
  created_at: string | null
  tenant_id?: string | null
}

export const adminsApi = {
  list: () => api.get<{ admins: AdminRecord[] }>('/api/auth/admins').then((r) => r.admins),

  create: (body: {
    username: string
    password: string
    role?: string
    permissions?: Record<string, boolean> | null
    email?: string | null
    tenant_id?: string | null
  }) =>
    api.post<{ status: string; username: string; role: string; permissions: Record<string, boolean>; tenant_id?: string | null }>(
      '/api/auth/create',
      body,
    ),

  update: (
    username: string,
    body: { role?: string; permissions?: Record<string, boolean>; email?: string | null; tenant_id?: string | null },
  ) =>
    api.patch<{ status: string; username: string; role: string; permissions: Record<string, boolean>; tenant_id?: string | null }>(
      `/api/auth/admins/${encodeURIComponent(username)}`,
      body,
    ),

  remove: (username: string) => api.del<{ status: string }>(`/api/auth/admins/${encodeURIComponent(username)}`),

  resetPassword: (username: string, newPassword: string) =>
    api.post<{ status: string }>(`/api/auth/admins/${encodeURIComponent(username)}/reset-password`, {
      new_password: newPassword,
    }),

  me: () => api.get<AdminIdentity>('/api/auth/me'),
}
