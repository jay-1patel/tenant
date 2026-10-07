import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll, beforeEach } from 'vitest'
import { fixtureServer } from './fixture-server'
import { testState } from './fixture-server'

beforeEach(() => {
  testState.reset()
})

afterEach(() => {
  cleanup()
})

beforeAll(() => {
  fixtureServer.install()
})

afterAll(() => {
  fixtureServer.restore()
})
