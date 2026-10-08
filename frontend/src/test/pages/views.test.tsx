import { describe, expect, it } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderApp, waitForScreen } from '../helpers'

const T = 'acme'

async function renderView(hash: string) {
  const utils = renderApp(hash)
  await waitForScreen()
  return utils
}

async function expectHeading(text: string | RegExp) {
  await waitFor(
    () => {
      expect(screen.getByRole('heading', { name: text })).toBeInTheDocument()
    },
    { timeout: 3000 },
  )
}

describe('tenant list page', () => {
  it('lists tenants', async () => {
    await renderView('#/tenants')
    await expectHeading('Tenants')
    expect((await screen.findAllByText('Acme Retail')).length).toBeGreaterThan(0)
  })
})

describe('tenant overview page', () => {
  it('shows overview', async () => {
    await renderView(`#/tenants/${T}/overview`)
    expect((await screen.findAllByText(/Acme/)).length).toBeGreaterThan(0)
  })
})

describe('profile page', () => {
  it('shows the profile editor', async () => {
    await renderView(`#/tenants/${T}/profile`)
    await expectHeading('Profile')
  })
})

describe('menu preview page', () => {
  it('shows the menu preview', async () => {
    await renderView(`#/tenants/${T}/menu`)
    await expectHeading('Menu')
  })
})

describe('menu editor page', () => {
  it('shows the menu editor', async () => {
    await renderView(`#/tenants/${T}/menu-edit`)
    await expectHeading('Menu editor')
  })
})

describe('intents and flows page', () => {
  it('shows flows', async () => {
    await renderView(`#/tenants/${T}/flows`)
    expect((await screen.findAllByText(/flow|intent/i)).length).toBeGreaterThan(0)
  })
})

describe('records page', () => {
  it('shows records (products for ecommerce)', async () => {
    await renderView(`#/tenants/${T}/records`)
    await expectHeading('Products')
    expect((await screen.findAllByText('Widget')).length).toBeGreaterThan(0)
  })
})

describe('offerings page', () => {
  it('shows offerings', async () => {
    await renderView(`#/tenants/${T}/offerings`)
    expect((await screen.findAllByText('Widget')).length).toBeGreaterThan(0)
  })
})

describe('customers page', () => {
  it('lists customers', async () => {
    await renderView(`#/tenants/${T}/customers`)
    expect((await screen.findAllByText('Priya')).length).toBeGreaterThan(0)
  })
})

describe('orders page', () => {
  it('lists orders', async () => {
    await renderView(`#/tenants/${T}/orders`)
    await expectHeading('Orders')
    expect(await screen.findByText('A-1')).toBeInTheDocument()
  })
})

describe('campaigns page', () => {
  it('lists campaigns and stats', async () => {
    await renderView(`#/tenants/${T}/campaigns`)
    expect(await screen.findByText('Diwali blast')).toBeInTheDocument()
  })
})

describe('distributors page', () => {
  it('lists distributors', async () => {
    await renderView(`#/tenants/${T}/distributors`)
    expect(await screen.findByText('Ravi Traders')).toBeInTheDocument()
  })
})

describe('chat history page', () => {
  it('lists conversation threads', async () => {
    await renderView(`#/tenants/${T}/chat-history`)
    expect((await screen.findAllByText('Priya')).length).toBeGreaterThan(0)
  })
})

describe('live inbox page', () => {
  it('shows the inbox queue', async () => {
    await renderView(`#/tenants/${T}/inbox`)
    await expectHeading('Live inbox')
    expect(await screen.findByText('I need help')).toBeInTheDocument()
  })
})

describe('complaints page', () => {
  it('lists complaints', async () => {
    await renderView(`#/tenants/${T}/complaints`)
    expect(await screen.findByText('T-1')).toBeInTheDocument()
  })
})

describe('uploads page', () => {
  it('lists uploaded files', async () => {
    await renderView(`#/tenants/${T}/uploads`)
    await expectHeading('Uploads')
    expect(await screen.findByText('faq.pdf')).toBeInTheDocument()
  })
})

describe('team chat page', () => {
  it('shows the admin chat panel', async () => {
    await renderView(`#/tenants/${T}/chat`)
    expect((await screen.findAllByText(/chat/i)).length).toBeGreaterThan(0)
  })
})

describe('versions page', () => {
  it('lists published versions', async () => {
    await renderView(`#/tenants/${T}/versions`)
    await expectHeading('Versions')
  })
})

describe('layers page', () => {
  it('shows profile layers', async () => {
    await renderView(`#/tenants/${T}/layers`)
    expect((await screen.findAllByText(/layer/i)).length).toBeGreaterThan(0)
  })
})

describe('tokens page', () => {
  it('lists API tokens', async () => {
    await renderView(`#/tenants/${T}/tokens`)
    await expectHeading('API tokens')
    expect(await screen.findByText('prod')).toBeInTheDocument()
  })
})

describe('test and smoke page', () => {
  it('shows the smoke report', async () => {
    await renderView(`#/tenants/${T}/test`)
    await expectHeading('Test and smoke')
  })
})

describe('team page', () => {
  it('shows team & permissions', async () => {
    await renderView('#/team')
    await expectHeading(/Team & permissions/)
    expect(await screen.findByText('helper')).toBeInTheDocument()
  })
})

describe('register page', () => {
  it('shows the register wizard', async () => {
    await renderView('#/register')
    await expectHeading('Register a tenant')
  })
})

describe('pending IT info pages', () => {
  for (const view of ['portfolio', 'technologies', 'careers', 'benefits']) {
    it(`${view} shows the coming-next notice`, async () => {
      await renderView(`#/tenants/${T}/${view}`)
      expect(await screen.findByText('Coming next')).toBeInTheDocument()
    })
  }
})

describe('unknown view', () => {
  it('shows the unknown-view alert', async () => {
    await renderView(`#/tenants/${T}/definitely-not-a-view`)
    expect(await screen.findByText('Unknown view')).toBeInTheDocument()
  })
})
