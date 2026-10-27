import { beforeEach, describe, expect, it, vi } from 'vitest'
import { screen, waitFor } from '@testing-library/react'

import { DocumentDialog } from '@/components/document-dialog'
import { renderWithProviders } from '@/test/utils'

const api = vi.hoisted(() => ({ download: vi.fn(), toastSuccess: vi.fn(), toastError: vi.fn() }))
vi.mock('@/lib/api', () => ({ documents: { download: api.download } }))
vi.mock('sonner', () => ({ toast: { success: api.toastSuccess, error: api.toastError } }))
vi.mock('@/hooks/use-display-locale', () => ({ useDisplayLocale: () => 'en-US' }))

const baseProps = { open: true, onClose: vi.fn() }

describe('DocumentDialog', () => {
  beforeEach(() => {
    vi.resetAllMocks()
    api.download.mockResolvedValue(undefined)
  })

  it('renders nothing while closed', () => {
    renderWithProviders(<DocumentDialog {...baseProps} open={false} />)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows report options with every report section checked', () => {
    renderWithProviders(<DocumentDialog {...baseProps} />)
    expect(screen.getByText('Generate document')).toBeInTheDocument()
    expect(screen.getByText('Net worth')).toBeInTheDocument()
    expect(screen.getByText('Recurring obligations')).toBeInTheDocument()
    expect(screen.queryByText('Savings suggestion')).not.toBeInTheDocument()
    expect(
      screen.getAllByRole('checkbox').every((box) => (box as HTMLInputElement).checked),
    ).toBe(true)
  })

  it('swaps the section set when the type changes to plan', async () => {
    const { user } = renderWithProviders(<DocumentDialog {...baseProps} />)
    await user.click(screen.getByText('Financial plan'))
    expect(screen.getByText('Goals')).toBeInTheDocument()
    expect(screen.getByText('Savings suggestion')).toBeInTheDocument()
    expect(screen.queryByText('Net worth')).not.toBeInTheDocument()
  })

  it('posts the chosen options and downloads the file', async () => {
    const { user } = renderWithProviders(<DocumentDialog {...baseProps} />)
    await user.click(screen.getByText('HTML'))
    await user.click(screen.getByText('Recurring obligations'))
    await user.type(screen.getByLabelText('Title (optional)'), 'Quarterly review')
    await user.click(screen.getByRole('button', { name: 'Generate' }))

    await waitFor(() => expect(api.download).toHaveBeenCalledTimes(1))
    expect(api.download).toHaveBeenCalledWith('report', {
      format: 'html',
      period: 'last_quarter',
      sections: ['net_worth', 'income_expenses', 'account_balances', 'large_transactions'],
      title: 'Quarterly review',
    })
    expect(api.toastSuccess).toHaveBeenCalled()
  })

  it('refuses to generate with every section unchecked', async () => {
    const { user } = renderWithProviders(<DocumentDialog {...baseProps} />)
    for (const box of screen.getAllByRole('checkbox')) {
      await user.click(box)
    }
    await user.click(screen.getByRole('button', { name: 'Generate' }))
    expect(screen.getByText('Select at least one section')).toBeInTheDocument()
    expect(api.download).not.toHaveBeenCalled()
  })

  it('requires both dates for a custom period', async () => {
    const { user } = renderWithProviders(<DocumentDialog {...baseProps} />)
    await user.click(screen.getByText('Custom'))
    await user.click(screen.getByRole('button', { name: 'Generate' }))
    expect(
      screen.getByText('Pick a start and end date for the custom period'),
    ).toBeInTheDocument()
    expect(api.download).not.toHaveBeenCalled()
  })

  it('shows the server error when generation fails', async () => {
    api.download.mockRejectedValue(new Error('boom'))
    const { user } = renderWithProviders(<DocumentDialog {...baseProps} />)
    await user.click(screen.getByRole('button', { name: 'Generate' }))
    await waitFor(() => expect(api.toastError).toHaveBeenCalled())
  })
})
