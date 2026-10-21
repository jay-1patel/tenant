import { writeFile } from 'node:fs/promises'

// Captures the admin panel pages for the generic user-onboarding guide.
// Mirrors capture-dashboard.mjs (same redaction rules) but walks every page in
// one session and prints a text manifest alongside each screenshot.

const baseUrl = 'https://prominent-faster-dropper.ngrok-free.dev'
const tenant = process.env.ONBOARD_TENANT || 'l'
const outDir = new URL('./assets/onboarding/', import.meta.url).pathname.replace(/^\/([A-Za-z]:)/, '$1')

const pages = await fetch('http://127.0.0.1:9222/json').then((r) => r.json())
const page = pages.find((item) => item.type === 'page' && item.url.startsWith(baseUrl))
if (!page) throw new Error('The Tenant Console page is not open in Chrome.')

const socket = new WebSocket(page.webSocketDebuggerUrl)
await new Promise((resolve, reject) => {
  socket.addEventListener('open', resolve, { once: true })
  socket.addEventListener('error', reject, { once: true })
})
let nextId = 0
const pending = new Map()
socket.addEventListener('message', (event) => {
  const message = JSON.parse(event.data)
  if (!message.id) return
  const waiter = pending.get(message.id)
  if (!waiter) return
  pending.delete(message.id)
  if (message.error) waiter.reject(new Error(message.error.message))
  else waiter.resolve(message.result)
})
function send(method, params = {}) {
  const id = ++nextId
  socket.send(JSON.stringify({ id, method, params }))
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }))
}
async function evaluate(expression) {
  const response = await send('Runtime.evaluate', {
    expression,
    awaitPromise: true,
    returnByValue: true,
    userGesture: true,
  })
  if (response.exceptionDetails) {
    throw new Error(response.exceptionDetails.exception?.description || response.exceptionDetails.text)
  }
  return response.result?.value
}
const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

await send('Page.enable')
await send('Runtime.enable')

const redact = String.raw`(() => {
  const replacements = [
    [/Superadmin123@/gi, 'Account owner'],
    [/\b[a-z0-9_.-]*admin(?:\s+\(approved\))?\b/gi, 'Account owner'],
    [/customercare@leewaysoftech\.com/gi, '[SUPPORT EMAIL]'],
    [/sales@leewaysoftech\.com/gi, '[SALES EMAIL]'],
    [/leewaysoftech\.com/gi, 'leewaysoftech.example'],
    [/\+?\d[\d ().-]{8,}\d/g, '[REDACTED]'],
  ];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    let value = node.nodeValue;
    for (const [pattern, replacement] of replacements) value = value.replace(pattern, replacement);
    node.nodeValue = value;
  }
  for (const element of document.querySelectorAll('*')) {
    for (const attr of Array.from(element.attributes)) {
      if (attr.name === 'value' || attr.name === 'placeholder' || attr.name === 'title') {
        let value = attr.value;
        for (const [pattern, replacement] of replacements) value = value.replace(pattern, replacement);
        element.setAttribute(attr.name, value);
      }
    }
    if (element.children.length === 0 && /superadmin123@|leewayadmin|leewaysoftech\.com/i.test(element.textContent || '')) {
      let value = element.textContent;
      for (const [pattern, replacement] of replacements) value = value.replace(pattern, replacement);
      element.textContent = value;
    }
  }
  for (const input of document.querySelectorAll('input')) {
    let value = input.value;
    for (const [pattern, replacement] of replacements) value = value.replace(pattern, replacement);
    if (input.type === 'email' || input.type === 'tel' || value.replace(/\D/g, '').length >= 10) value = '[REDACTED]';
    input.value = value;
    input.setAttribute('value', value);
  }
  let style = document.getElementById('report-screenshot-sanitize');
  if (!style) { style = document.createElement('style'); style.id = 'report-screenshot-sanitize'; document.head.appendChild(style); }
  style.textContent = 'aside { display: none !important } main { height: auto !important; min-height: 100vh !important; max-height: none !important; overflow: visible !important } body, #root, #root > div { height: auto !important; min-height: 100vh !important; overflow: visible !important } .screenshot-redacted-input { color: transparent !important; text-shadow: none !important; }';
  for (const input of document.querySelectorAll('input[type="tel"], input[type="email"]')) { input.value = '[REDACTED]'; input.setAttribute('value', '[REDACTED]'); }
})()`

async function shot(name, route) {
  await send('Emulation.setDeviceMetricsOverride', { width: 1600, height: 1900, deviceScaleFactor: 1, mobile: false })
  await evaluate(`location.hash = ${JSON.stringify(route)}`)
  await pause(2600)
  const text = await evaluate('document.body.innerText')
  await evaluate(redact)
  await pause(250)
  const result = await send('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false, fromSurface: true })
  const path = outDir + name + '.png'
  await writeFile(path, Buffer.from(result.data, 'base64'))
  console.log(JSON.stringify({ name, route, firstText: text.slice(0, 120).replace(/\n/g, ' | ') }))
}

// 1. Login screen, before any session exists.
await evaluate(`(() => { localStorage.removeItem('tenant-console.token'); localStorage.removeItem('tenant-console.tenant'); return true; })()`)
await evaluate(`location.hash = '#/tenants'`)
await pause(2500)
await shot('login', '#/tenants')

// 2. Restore the session.
const username = process.env.DASHBOARD_USERNAME
const password = process.env.DASHBOARD_PASSWORD
const login = await evaluate(`(async () => {
  const response = await fetch('/api/auth/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
    body: JSON.stringify({ username: ${JSON.stringify(username)}, password: ${JSON.stringify(password)} })
  });
  const body = await response.json();
  if (!response.ok) throw new Error(body.detail || 'Dashboard sign-in failed');
  localStorage.setItem('tenant-console.token', body.token);
  localStorage.setItem('tenant-console.tenant', ${JSON.stringify(tenant)});
  location.reload();
  return { role: body.role };
})()`)
console.log(JSON.stringify({ login }))
// The SPA reads the token at mount, so it needs a fresh boot before shooting.
await pause(6000)

// 3. Walk every console page.
const routes = [
  ['tenant-list', '#/tenants'],
  ['register', '#/register'],
  ['tenant-requests', '#/tenant-requests'],
  ['api-requests', '#/api-requests'],
  ['audit-history', '#/audit-history'],
  ['team', '#/team'],
  ['overview', `#/tenants/${tenant}/overview`],
  ['records', `#/tenants/${tenant}/records`],
  ['customers', `#/tenants/${tenant}/customers`],
  ['profile', `#/tenants/${tenant}/profile`],
  ['menu', `#/tenants/${tenant}/menu`],
  ['menu-edit', `#/tenants/${tenant}/menu-edit`],
  ['intents', `#/tenants/${tenant}/intents`],
  ['uploads', `#/tenants/${tenant}/uploads`],
  ['chat', `#/tenants/${tenant}/chat`],
  ['chat-history', `#/tenants/${tenant}/chat-history`],
  ['inbox', `#/tenants/${tenant}/inbox`],
  ['complaints', `#/tenants/${tenant}/complaints`],
  ['callbacks', `#/tenants/${tenant}/callbacks`],
  ['tokens', `#/tenants/${tenant}/tokens`],
  ['api-access', `#/tenants/${tenant}/api-access`],
  ['versions', `#/tenants/${tenant}/versions`],
  ['layers', `#/tenants/${tenant}/layers`],
  ['test', `#/tenants/${tenant}/test`],
]
for (const [name, route] of routes) {
  await shot(name, route)
}
socket.close()
console.log('DONE')
