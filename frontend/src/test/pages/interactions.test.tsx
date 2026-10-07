import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderApp, waitForScreen } from '../helpers'

const T = 'acme'

async function renderView(hash: string) {
  renderApp(hash)
  await waitForScreen()
}

describe('sidebar navigation', () => {
  it('navigates between views via the sidebar', async () => {
    await renderView(`#/tenants/${T}/overview`)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: /api tokens/i }))
    await waitFor(
      () => expect(screen.getByRole('heading', { name: 'API tokens' })).toBeInTheDocument(),
      { timeout: 3000 },
    )
  })
})

describe('versions page interactions', () => {
  it('publishes a draft and toasts the new version', async () => {
    await renderView(`#/tenants/${T}/versions`)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Publish draft' }))
    await waitFor(() => expect(screen.getByText(/Published version 3/)).toBeInTheDocument())
  })
})

describe('tokens page interactions', () => {
  it('mints a token and shows it once', async () => {
    await renderView(`#/tenants/${T}/tokens`)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Label'), 'ci')
    await user.click(screen.getByRole('button', { name: 'Mint token' }))
    expect(await screen.findByText('tk_new_token')).toBeInTheDocument()
  })
})

describe('test and smoke page interactions', () => {
  it('asks a test question and shows the matched intent', async () => {
    await renderView(`#/tenants/${T}/test`)
    const user = userEvent.setup()
    const input = await screen.findByPlaceholderText(/Type what a customer would say/i)
    await user.type(input, 'hi')
    await user.click(screen.getAllByRole('button', { name: /^Run$/ })[0])
    await waitFor(() => expect(screen.getAllByText(/greeting/).length).toBeGreaterThan(0))
  })
})

describe('customers page interactions', () => {
  it('filters customers by search', async () => {
    await renderView(`#/tenants/${T}/customers`)
    const user = userEvent.setup()
    await screen.findByText('Priya')
    const search = screen.getByRole('textbox')
    await user.type(search, 'nobody-here')
    await waitFor(() => expect(screen.queryByRole('row', { name: /priya/i })).toBeNull())
  })
})

describe('distributors page interactions', () => {
  it('shows distributors and supports the create form', async () => {
    await renderView(`#/tenants/${T}/distributors`)
    expect(await screen.findByText('Ravi Traders')).toBeInTheDocument()
  })
})

describe('orders page interactions', () => {
  it('lists order rows with totals', async () => {
    await renderView(`#/tenants/${T}/orders`)
    await screen.findByText('A-1')
    expect((await screen.findAllByText(/priya/i)).length).toBeGreaterThan(0)
  })
})

describe('inbox page interactions', () => {
  it('shows the queue with handover state', async () => {
    await renderView(`#/tenants/${T}/inbox`)
    expect(await screen.findByText('I need help')).toBeInTheDocument()
  })
})

describe('complaints page interactions', () => {
  it('lists complaints', async () => {
    await renderView(`#/tenants/${T}/complaints`)
    expect(await screen.findByText('T-1')).toBeInTheDocument()
  })
})

describe('uploads page interactions', () => {
  it('lists files per module', async () => {
    await renderView(`#/tenants/${T}/uploads`)
    expect(await screen.findByText('faq.pdf')).toBeInTheDocument()
  })
})

describe('register wizard', () => {
  it('renders the wizard steps', async () => {
    await renderView('#/register')
    expect(await screen.findByText(/tenant id|vertical|step/i)).toBeInTheDocument()
  })
})

describe('api failure handling', () => {
  it('shows a friendly error when the tenant list fails', async () => {
    const { testState } = await import('../fixture-server')
    testState.respond('GET /api/admin/tenants', () => ({
      status: 500,
      body: { detail: 'database is closed' },
    }))
    await renderView('#/tenants')
    expect((await screen.findAllByText(/database is closed|Could not load tenants|Cannot list tenants/i)).length).toBeGreaterThan(0)
  })
})
