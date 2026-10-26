import { screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { admin, type SimplefinSettings } from '@/lib/api'
import { renderWithProviders } from '@/test/utils'

import { SimplefinSettings as SimplefinSettingsSection } from './simplefin-settings'

vi.mock('@/lib/api', () => ({
  admin: {
    simplefinSettings: vi.fn(),
    updateSimplefinSettings: vi.fn(),
  },
}))

const disabledSettings: SimplefinSettings = {
  simplefin_enabled: false,
  simplefin_api_url: 'https://beta-bridge.simplefin.org',
}

const enabledSettings: SimplefinSettings = {
  simplefin_enabled: true,
  simplefin_api_url: 'https://bridge.simplefin.org',
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(admin.simplefinSettings).mockResolvedValue(disabledSettings)
  vi.mocked(admin.updateSimplefinSettings).mockResolvedValue(enabledSettings)
})

it('loads the effective settings and saves the toggle plus URL', async () => {
  const { user } = renderWithProviders(<SimplefinSettingsSection />)

  const apiUrl = await screen.findByLabelText('Bridge URL')
  expect(apiUrl).toHaveValue('https://beta-bridge.simplefin.org')
  const toggle = screen.getByRole('switch', { name: 'Enable SimpleFIN' })
  expect(toggle).toHaveAttribute('aria-checked', 'false')

  await user.click(toggle)
  await user.clear(apiUrl)
  await user.type(apiUrl, 'https://bridge.simplefin.org')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(admin.updateSimplefinSettings).toHaveBeenCalledOnce())
  expect(vi.mocked(admin.updateSimplefinSettings).mock.calls[0][0]).toEqual({
    simplefin_enabled: true,
    simplefin_api_url: 'https://bridge.simplefin.org',
  })
})

it('renders an enabled saved configuration', async () => {
  vi.mocked(admin.simplefinSettings).mockResolvedValue(enabledSettings)

  renderWithProviders(<SimplefinSettingsSection />)

  expect(await screen.findByLabelText('Bridge URL')).toHaveValue(
    'https://bridge.simplefin.org',
  )
  expect(screen.getByRole('switch', { name: 'Enable SimpleFIN' })).toHaveAttribute(
    'aria-checked',
    'true',
  )
})
