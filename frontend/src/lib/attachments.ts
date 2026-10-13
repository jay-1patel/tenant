/**
 * Chat attachments for the internal admin chat and the live inbox.
 *
 * Both upload a file to a tenant-scoped endpoint that hosts it publicly
 * (imghippo for images, catbox otherwise) and returns a descriptor. The
 * descriptor is embedded in the admin-chat message, or turned into a link in
 * the inbox reply — WhatsApp media sending is disabled project-wide.
 */

import { api } from './api'
import { readAsBase64 } from './uploads'

const base = (tenantId: string) => `/api/admin/tenants/${encodeURIComponent(tenantId)}`

/** Keep in step with `MAX_ATTACHMENT_BYTES` in `backend/routes/admin.py`. */
export const MAX_ATTACHMENT_BYTES = 15 * 1024 * 1024
export const MAX_ATTACHMENT_LABEL = `${MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB`

/** What the file picker offers and what the hint tells the admin. */
export const ATTACHMENT_ACCEPT = 'image/*,.pdf,.doc,.docx,.txt,.xlsx,.xls'
export const ATTACHMENT_TYPES_LABEL =
  'Images (JPG, PNG, GIF, WEBP, BMP) and documents (PDF, DOC, DOCX, TXT, XLS, XLSX)'

export interface Attachment {
  url: string
  name: string
  type: string
  size: number
  media_type?: string
}

export const attachmentsApi = {
  upload: async (tenantId: string, file: File, area: 'chat' | 'inbox'): Promise<Attachment> => {
    if (file.size > MAX_ATTACHMENT_BYTES) {
      throw new Error(`Attachments must be under ${MAX_ATTACHMENT_BYTES / (1024 * 1024)} MB`)
    }
    const content = await readAsBase64(file)
    const suffix = area === 'chat' ? 'chat/attach' : 'inbox/attach'
    return api.post<Attachment>(`${base(tenantId)}/${suffix}`, {
      filename: file.name,
      content,
      media_type: file.type || undefined,
    })
  },
}
