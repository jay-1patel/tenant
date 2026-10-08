/**
 * A tiny in-test HTTP layer: replaces global fetch with a routing table so
 * every screen can be exercised against realistic API payloads without a
 * backend. Tests can override any route's response via `testState.respond`.
 */
import { vi } from 'vitest'
import { fixtures } from './fixtures'

type Handler = (ctx: {
  url: URL
  method: string
  body: any
}) => { status?: number; body: unknown } | Promise<{ status?: number; body: unknown }>

interface State {
  calls: { method: string; path: string; body?: unknown }[]
  respond: (methodAndPath: string, handler: Handler) => void
  reset: () => void
}

const overrides = new Map<string, Handler>()

const json = (body: unknown, status = 200) => ({ status, body })

export const testState: State = {
  calls: [],
  respond(methodAndPath, handler) {
    overrides.set(methodAndPath, handler)
  },
  reset() {
    testState.calls.length = 0
    overrides.clear()
  },
}

function resolve(method: string, path: string, body: unknown) {
  const url = new URL(path, 'http://localhost')
  const pathOnly = url.pathname
  const overrideKey = [...overrides.keys()].find((k) => {
    const [m, p] = k.split(' ')
    if (m !== method) return false
    if (p.endsWith('*')) return pathOnly.startsWith(p.substring(0, p.length - 1))
    return p === pathOnly
  })
  const handler = overrideKey ? overrides.get(overrideKey) : undefined
  if (handler) return handler({ url, method, body })
  return routeDefault(method, pathOnly, url, body)
}

function routeDefault(
  method: string,
  path: string,
  _url: URL,
  body: any,
): { status?: number; body: unknown } {
  // ── auth ──────────────────────────────────────────────────────────────
  if (path === '/api/auth/status') return json({ has_admins: true })
  if (path === '/api/auth/login' && method === 'POST') return json({ token: 'test-token' })
  if (path === '/api/auth/me')
    return json(fixtures.identity)
  if (path === '/api/auth/first-admin' && method === 'POST')
    return json({ token: 'test-token' })
  if (path === '/api/auth/create' && method === 'POST')
    return json({ status: 'created', username: body?.username, role: body?.role ?? 'sub_admin', permissions: body?.permissions ?? {} })
  if (path === '/api/auth/admins') return json({ admins: fixtures.admins })
  const adminMatch = path.match(/^\/api\/auth\/admins\/([^/]+)$/)
  if (adminMatch) {
    const username = decodeURIComponent(adminMatch[1])
    if (method === 'DELETE')
      return json({ status: `removed ${username}` })
    if (method === 'PATCH')
      return json({ status: 'updated', username, role: body?.role ?? 'sub_admin', permissions: body?.permissions ?? {} })
  }
  if (path.match(/^\/api\/auth\/admins\/[^/]+\/reset-password$/) && method === 'POST')
    return json({ status: 'password reset' })

  // ── tenants ─────────────────────────────────────────────────────────
  if (path === '/api/admin/tenants' && method === 'GET') return json({ tenants: fixtures.tenants })
  if (path === '/api/admin/tenants' && method === 'POST')
    return json({ ok: true, tenant: { ...fixtures.tenant, ...body } })
  const m = path.match(/^\/api\/admin\/tenants\/([^/]+)(\/.*)?$/)
  if (m) {
    const id = decodeURIComponent(m[1])
    const sub = m[2] ?? ''
    if (sub === '' && method === 'DELETE') return json({ ok: true })
    if (sub === '' && method === 'GET')
      return json({ count: fixtures.offerings.length, columns: fixtures.recordSchema.columns, offerings: fixtures.offerings })
    if (sub === '/phone-id' && method === 'POST') return json({ ok: true })
    if (sub === '/detail') return json(fixtures.layerDetail)
    if (sub === '/resolved') return json(fixtures.resolved)
    if (sub === '/profile' && method === 'PUT') return json({ ok: true, validation: [] })
    if (sub === '/publish') return json({ ok: true, version: 3, active_intents: ['greeting'], visible_buttons: ['menu_help'] })
    if (sub === '/versions' && method === 'GET') return json(fixtures.versions)
    if (sub === '/versions' && method === 'POST') return json({ ok: true, version: 3, active: 3 })
    const vm = sub.match(/^\/versions\/(\d+)$/)
    if (vm) return json(fixtures.versionSnapshot)
    if (sub === '/rollback' && method === 'POST') return json({ ok: true, version: body?.version ?? 2, active: body?.version ?? 2 })
    if (sub === '/tokens' && method === 'GET') return json({ tenant_id: id, tokens: fixtures.tokens })
    if (sub === '/tokens' && method === 'POST')
      return json({ ok: true, id: 99, token: 'tk_new_token', warning: 'Copy it now' })
    const tm = sub.match(/^\/tokens\/(\d+)$/)
    if (tm && method === 'DELETE') return json({ ok: true })
    if (sub === '/test-question' && method === 'POST')
      return json({ tenant_id: id, message: body?.message ?? '', intent: 'greeting', score: 0.9, tier: 'high', flow: null, active_intents: ['greeting'] })
    if (sub === '/smoke') return json(fixtures.smoke)
    if (sub === '/offerings' && method === 'GET') return json({ offerings: fixtures.offerings, columns: fixtures.recordSchema.columns, count: fixtures.offerings.length })
    if (sub === '/offerings' && method === 'POST') return json({ ok: true, id: 42 })
    const om = sub.match(/^\/offerings\/(\d+)$/)
    if (om && method === 'PUT') return json({ ok: true })
    if (om && method === 'DELETE') return json({ ok: true })
    if (sub === '/offerings/reorder' && method === 'POST') return json({ ok: true })
    if (sub === '/record-schema' && method === 'GET') return json(fixtures.recordSchema)
    if (sub === '/record-schema/columns' && method === 'POST') return json({ ok: true, id: 10 })
    const cm = sub.match(/^\/record-schema\/columns\/([^/]+)$/)
    if (cm) {
      if (method === 'PUT') return json({ ok: true })
      if (method === 'DELETE') return json({ ok: true })
    }
    if (sub === '/record-schema/reset' && method === 'POST') return json({ ok: true })
    const rcm = sub.match(/^\/records(\/(\d+))?$/)
    if (rcm) {
      if (method === 'GET') return json({ records: fixtures.records, count: fixtures.records.length })
      if (method === 'POST') return json({ ok: true, id: 50 })
      if (method === 'PUT') return json({ ok: true })
      if (method === 'DELETE') return json({ ok: true })
    }
    if (sub === '/conversations' && method === 'GET')
      return json({ conversations: fixtures.threads, count: fixtures.threads.length })
    const convMatch = sub.match(/^\/conversations\/([^/]+)$/)
    if (convMatch && method === 'GET') return json({ turns: fixtures.turns })
    if (sub === '/chat-history' && method === 'GET')
      return json({ history: fixtures.turns })
    if (sub === '/inbox' && method === 'GET') return json({ queue: fixtures.inbox })
    if (sub === '/agents' && method === 'GET') return json({ agents: fixtures.agents })
    const inboxReply = sub.match(/^\/inbox\/([^/]+)\/reply$/)
    if (inboxReply && method === 'POST') return json({ status: 'sent' })
    if (sub === '/inbox/assign' && method === 'POST') return json({ status: 'assigned' })
    const handover = sub.match(/^\/inbox\/handover\/(.+)$/)
    if (handover && method === 'POST') return json({ status: 'updated' })
    const resolveInbox = sub.match(/^\/inbox\/resolve\/(.+)$/)
    if (resolveInbox && (method === 'POST' || method === 'DELETE')) return json({ status: 'resolved' })
    if (sub === '/complaints' && method === 'GET') return json({ complaints: fixtures.complaints })
    const complaintMatch = sub.match(/^\/complaints\/([^/]+)$/)
    if (complaintMatch) {
      if (method === 'PUT') return json({ status: 'updated' })
      if (method === 'DELETE') return json({ status: 'deleted' })
    }
    const complaintReply = sub.match(/^\/complaints\/([^/]+)\/reply$/)
    if (complaintReply && method === 'POST') return json({ status: 'sent' })
    if (sub === '/campaigns' && method === 'GET') return json({ campaigns: fixtures.campaigns, stats: fixtures.campaignStats })
    if (sub === '/campaigns' && method === 'POST') return json({ ok: true, id: 7 })
    const campMatch = sub.match(/^\/campaigns\/(\d+)$/)
    if (campMatch) {
      if (method === 'PUT') return json({ ok: true })
      if (method === 'DELETE') return json({ ok: true })
    }
    if (sub === '/distributors' && method === 'GET') return json({ distributors: fixtures.distributors })
    if (sub === '/distributors' && method === 'POST') return json({ ok: true, wa_id: body?.wa_id })
    const distMatch = sub.match(/^\/distributors\/([^/]+)$/)
    if (distMatch) {
      if (method === 'PUT') return json({ ok: true })
      if (method === 'DELETE') return json({ ok: true })
    }
    if (sub === '/files' && method === 'GET') return json({ files: fixtures.files })
    if (sub === '/files/upload' && method === 'POST') return json({ status: 'uploaded', filename: 'a.pdf', chunks: 3, size: 1234, file_url: '/f' })
    const fileMatch = sub.match(/^\/files\/([^/]+)(\/(preview|download))?$/)
    if (fileMatch) {
      if (method === 'DELETE') return json({ status: 'deleted' })
      return json({ url: 'http://localhost/blob' })
    }
    if (sub === '/chat/users' && method === 'GET') return json({ users: fixtures.chatUsers })
    if (sub === '/chat/send' && method === 'POST') return json({ status: 'sent', reply: 'Hello!' })
  }

  // ── shared platform tables ────────────────────────────────────────────
  if (path === '/api/admin/customers') return json({ customers: fixtures.customers, count: fixtures.customers.length })
  if (path === '/api/orders') return json({ orders: fixtures.orders, count: fixtures.orders.length, counts: fixtures.orderCounts })

  return json({ detail: `No test fixture for ${method} ${path}` }, 404)
}

export const fixtureServer = {
  originalFetch: globalThis.fetch,
  install() {
    globalThis.fetch = vi.fn(async (input: any, init?: RequestInit) => {
      const path = typeof input === 'string' ? input : input.url
      const method = (init?.method ?? 'GET').toUpperCase()
      let body: unknown
      if (init?.body) {
        try {
          body = JSON.parse(String(init.body))
        } catch {
          body = init.body
        }
      }
      testState.calls.push({ method, path, body })
      const result = await resolve(method, path, body)
      const status = result.status ?? 200
      return {
        ok: status >= 200 && status < 300,
        status,
        statusText: status === 200 ? 'OK' : 'Error',
        json: async () => result.body,
        text: async () => JSON.stringify(result.body),
      } as Response
    }) as unknown as typeof fetch
  },
  restore() {
    globalThis.fetch = fixtureServer.originalFetch
  },
}

