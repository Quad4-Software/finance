import { screen, waitFor } from '@testing-library/react'
import { beforeEach, expect, it, vi } from 'vitest'

import { admin, type BackupSettings } from '@/lib/api'
import { renderWithProviders } from '@/test/utils'

import { BackupSettings as BackupSettingsSection } from './backup-settings'

vi.mock('@/lib/api', () => ({
  admin: {
    backupSettings: vi.fn(),
    updateBackupSettings: vi.fn(),
    testBackupS3: vi.fn(),
    runBackupNow: vi.fn(),
  },
}))

const localSettings: BackupSettings = {
  storage_provider: 'local',
  backup_schedule_hour: 3,
  backup_retention_count: 14,
  backup_local_path: './data/backups',
  backup_encryption_key_set: true,
  storage_s3_bucket: '',
  storage_s3_region: '',
  storage_s3_endpoint_url: '',
  storage_s3_access_key_set: false,
  storage_s3_secret_key_set: false,
}

const s3Settings: BackupSettings = {
  ...localSettings,
  storage_provider: 's3',
  storage_s3_bucket: 'quad4-backups',
  storage_s3_region: 'eu-west-1',
  storage_s3_access_key_set: true,
  storage_s3_secret_key_set: true,
}

beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(admin.backupSettings).mockResolvedValue(localSettings)
  vi.mocked(admin.updateBackupSettings).mockResolvedValue(localSettings)
  vi.mocked(admin.testBackupS3).mockResolvedValue({ success: true, error: null })
  vi.mocked(admin.runBackupNow).mockResolvedValue({ task_id: 'task-1', status: 'queued' })
})

it('loads the effective settings and saves without touching blank secrets', async () => {
  const { user } = renderWithProviders(<BackupSettingsSection />)

  const retention = await screen.findByLabelText('Backups to keep')
  expect(retention).toHaveValue(14)
  // A configured encryption key is reported, never shown.
  expect(screen.getByText('Configured')).toBeInTheDocument()

  await user.clear(retention)
  await user.type(retention, '30')
  await user.click(screen.getByRole('button', { name: 'Save' }))

  await waitFor(() => expect(admin.updateBackupSettings).toHaveBeenCalledOnce())
  const payload = vi.mocked(admin.updateBackupSettings).mock.calls[0][0]
  expect(payload).toMatchObject({
    storage_provider: 'local',
    backup_schedule_hour: 3,
    backup_retention_count: 30,
    backup_local_path: './data/backups',
  })
  expect(payload).not.toHaveProperty('backup_encryption_key')
  expect(payload).not.toHaveProperty('storage_s3_access_key')
  expect(payload).not.toHaveProperty('storage_s3_secret_key')
})

it('shows the S3 fields and the connection test result', async () => {
  vi.mocked(admin.backupSettings).mockResolvedValue(s3Settings)
  vi.mocked(admin.testBackupS3).mockResolvedValue({ success: false, error: 'endpoint unreachable' })

  const { user } = renderWithProviders(<BackupSettingsSection />)

  expect(await screen.findByLabelText('Bucket')).toHaveValue('quad4-backups')
  expect(screen.getByLabelText('Region')).toHaveValue('eu-west-1')
  // Both S3 secrets report configured.
  expect(screen.getAllByText('Configured')).toHaveLength(3)

  await user.click(screen.getByRole('button', { name: 'Test S3 connection' }))

  await waitFor(() => expect(admin.testBackupS3).toHaveBeenCalledOnce())
  expect(vi.mocked(admin.testBackupS3).mock.calls[0][0]).toMatchObject({
    storage_s3_bucket: 'quad4-backups',
    storage_s3_region: 'eu-west-1',
  })
  expect(await screen.findByText('endpoint unreachable')).toBeInTheDocument()
})

it('queues a backup run', async () => {
  const { user } = renderWithProviders(<BackupSettingsSection />)

  await user.click(await screen.findByRole('button', { name: 'Run backup now' }))

  await waitFor(() => expect(admin.runBackupNow).toHaveBeenCalledOnce())
})
