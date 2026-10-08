import { describe, expect, it, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { setToken } from '@/lib/api'
import { renderWithShell, waitForScreen } from '../helpers'

describe('login screen', () => {
  beforeEach(() => {
    setToken(null)
    window.location.hash = '#/tenants'
  })

  it('shows the login form when unauthenticated', async () => {
    renderWithShell()
    await waitForScreen()
    expect(await screen.findByRole('heading', { name: 'Tenant Console' })).toBeInTheDocument()
    expect(screen.getByLabelText(/username/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('signs in with credentials and lands on the tenant list', async () => {
    renderWithShell()
    await waitForScreen()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText(/username/i), 'root')
    await user.type(screen.getByLabelText(/password/i), 'secret-password')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    await waitFor(
      () => expect(screen.getByRole('heading', { name: 'Tenants' })).toBeInTheDocument(),
      { timeout: 3000 },
    )
  })

  it('surfaces a backend login failure', async () => {
    const { testState } = await import('../fixture-server')
    testState.respond('POST /api/auth/login', () => ({ status: 401, body: { detail: 'Bad credentials' } }))
    renderWithShell()
    await waitForScreen()
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText(/username/i), 'root')
    await user.type(screen.getByLabelText(/password/i), 'wrong')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByText('Bad credentials')).toBeInTheDocument()
  })
})
