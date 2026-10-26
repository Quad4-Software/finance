import { act, screen } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'
import { renderWithProviders } from '@/test/utils'
import { ConnectorSelectDialog } from './connector-select-dialog'
import { OAuthConnectDialog } from './oauth-connect-dialog'

const api = vi.hoisted(() => ({ getProviders: vi.fn(), listInstitutions: vi.fn(), getReconnectToken: vi.fn(), getConnectToken: vi.fn(), toastError: vi.fn() }))
vi.mock('@/lib/api', () => ({ connections: api, auth: api }))
vi.mock('sonner', () => ({ toast: { error: api.toastError } }))

beforeEach(() => { vi.resetAllMocks() })

it('ignores provider responses from a closed session when reopened', async () => {
  let finish!: (data: unknown) => void
  api.getProviders.mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    .mockResolvedValueOnce([{ name: 'new', display_name: 'New provider', description: 'Synthetic', configured: true }])
  const props = { onClose: vi.fn(), onSelect: vi.fn() }
  const { rerender } = renderWithProviders(<ConnectorSelectDialog open {...props} />)
  rerender(<ConnectorSelectDialog open={false} {...props} />)
  rerender(<ConnectorSelectDialog open {...props} />)
  await screen.findByText('New provider')
  await act(async () => { finish([{ name: 'old', display_name: 'Old provider', configured: true }]) })
  expect(screen.queryByText('Old provider')).not.toBeInTheDocument()
  expect(screen.getByText('New provider')).toBeInTheDocument()
})

it('ignores an earlier country request after back navigation and another selection', async () => {
  let finish!: (data: unknown) => void
  api.listInstitutions.mockResolvedValueOnce({ countries: ['DE', 'GB'] })
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
    .mockResolvedValueOnce({ institutions: [{ country: 'GB', name: 'new', display_name: 'New bank' }] })
  const { user } = renderWithProviders(<OAuthConnectDialog open provider="synthetic" onClose={vi.fn()} />)
  await user.click(await screen.findByText('DE'))
  await user.click(screen.getByRole('button', { name: 'Back' }))
  await user.click(screen.getByText('GB'))
  await screen.findByText('New bank')
  await act(async () => { finish({ institutions: [{ country: 'DE', name: 'old', display_name: 'Old bank' }] }) })
  expect(screen.queryByText('Old bank')).not.toBeInTheDocument()
  expect(screen.getByText('New bank')).toBeInTheDocument()
})

it('waits for banks in the remembered country instead of showing an empty result', async () => {
  localStorage.setItem('quad4:lastOAuthCountry', 'DE')
  let finish!: (data: unknown) => void
  api.listInstitutions.mockResolvedValueOnce({ countries: ['DE'] })
    .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
  renderWithProviders(<OAuthConnectDialog open provider="synthetic" onClose={vi.fn()} />)
  await screen.findByRole('button', { name: 'Back' })
  expect(screen.queryByText('No institutions found.')).not.toBeInTheDocument()
  await act(async () => { finish({ institutions: [{ country: 'DE', name: 'bank', display_name: 'Remembered bank' }] }) })
  expect(screen.getByText('Remembered bank')).toBeInTheDocument()
})
