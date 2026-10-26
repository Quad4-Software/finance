import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, DatabaseBackup, Play, PlugZap, Save, XCircle } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  admin,
  type BackupSettings as BackupSettingsData,
  type BackupSettingsUpdate,
  type BackupS3TestResult,
} from '@/lib/api'

export function BackupSettings() {
  const { t } = useTranslation()
  const settingsQuery = useQuery({
    queryKey: ['admin', 'backup-settings'],
    queryFn: admin.backupSettings,
  })
  const setting = settingsQuery.data

  return (
    <section className="mb-8 rounded-xl border border-border/60 bg-card overflow-hidden">
      <div className="px-5 py-4 border-b border-border/40">
        <div className="flex items-center gap-2 mb-0.5">
          <DatabaseBackup size={15} className="text-muted-foreground" />
          <h2 className="text-sm font-semibold text-foreground">
            {t('admin.settings.backupTitle')}
          </h2>
        </div>
        <p className="text-xs text-muted-foreground">{t('admin.settings.backupSubtitle')}</p>
      </div>
      {settingsQuery.isError ? (
        <div role="alert" className="flex flex-wrap items-center gap-3 p-5 text-sm text-destructive">
          <span>{t('common.error')}</span>
          <Button variant="outline" size="sm" onClick={() => settingsQuery.refetch()}>
            {t('common.retry')}
          </Button>
        </div>
      ) : !setting ? (
        <div className="p-5 space-y-3">
          <Skeleton className="h-9 w-full rounded-lg" />
          <Skeleton className="h-9 w-full rounded-lg" />
        </div>
      ) : (
        // Remounting on new server data clears the secret drafts and resets
        // the fields, including the "configured" indicators.
        <BackupSettingsForm key={JSON.stringify(setting)} initial={setting} />
      )}
    </section>
  )
}

function BackupSettingsForm({ initial }: { initial: BackupSettingsData }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [provider, setProvider] = useState(initial.storage_provider)
  const [scheduleHour, setScheduleHour] = useState(String(initial.backup_schedule_hour))
  const [retention, setRetention] = useState(String(initial.backup_retention_count))
  const [localPath, setLocalPath] = useState(initial.backup_local_path)
  const [encryptionKey, setEncryptionKey] = useState('')
  const [s3Bucket, setS3Bucket] = useState(initial.storage_s3_bucket)
  const [s3Region, setS3Region] = useState(initial.storage_s3_region)
  const [s3Endpoint, setS3Endpoint] = useState(initial.storage_s3_endpoint_url)
  const [s3AccessKey, setS3AccessKey] = useState('')
  const [s3SecretKey, setS3SecretKey] = useState('')
  const [testResult, setTestResult] = useState<BackupS3TestResult | null>(null)

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: BackupSettingsUpdate = {
        storage_provider: provider,
        backup_schedule_hour: Number(scheduleHour),
        backup_retention_count: Number(retention),
        backup_local_path: localPath,
        storage_s3_bucket: s3Bucket,
        storage_s3_region: s3Region,
        storage_s3_endpoint_url: s3Endpoint,
      }
      // Secrets only travel when the admin typed a new value; blank keeps
      // whatever is configured.
      if (encryptionKey) payload.backup_encryption_key = encryptionKey
      if (s3AccessKey) payload.storage_s3_access_key = s3AccessKey
      if (s3SecretKey) payload.storage_s3_secret_key = s3SecretKey
      return admin.updateBackupSettings(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'backup-settings'] })
      toast.success(t('admin.settings.updated'))
    },
    onError: () => toast.error(t('common.error')),
  })

  const testMutation = useMutation({
    mutationFn: () =>
      admin.testBackupS3({
        storage_s3_bucket: s3Bucket || undefined,
        storage_s3_region: s3Region || undefined,
        storage_s3_endpoint_url: s3Endpoint || undefined,
        storage_s3_access_key: s3AccessKey || undefined,
        storage_s3_secret_key: s3SecretKey || undefined,
      }),
    onSuccess: setTestResult,
    onError: () => setTestResult({ success: false, error: t('common.error') }),
  })

  const runMutation = useMutation({
    mutationFn: admin.runBackupNow,
    onSuccess: () => toast.success(t('admin.settings.backupRunQueued')),
    onError: () => toast.error(t('common.error')),
  })

  return (
    <div className="p-5 space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="space-y-1.5">
          <Label className="text-xs">{t('admin.settings.backupProvider')}</Label>
          <Select value={provider} onValueChange={(v) => setProvider(v as 'local' | 's3')}>
            <SelectTrigger aria-label={t('admin.settings.backupProvider')} className="h-9 rounded-lg">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="local">{t('admin.settings.backupProviderLocal')}</SelectItem>
              <SelectItem value="s3">{t('admin.settings.backupProviderS3')}</SelectItem>
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="backup-schedule-hour" className="text-xs">
            {t('admin.settings.backupScheduleHour')}
          </Label>
          <Input
            id="backup-schedule-hour"
            type="number"
            min={0}
            max={23}
            value={scheduleHour}
            onChange={(e) => setScheduleHour(e.target.value)}
            className="h-9 rounded-lg"
          />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="backup-retention" className="text-xs">
            {t('admin.settings.backupRetention')}
          </Label>
          <Input
            id="backup-retention"
            type="number"
            min={1}
            value={retention}
            onChange={(e) => setRetention(e.target.value)}
            className="h-9 rounded-lg"
          />
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {provider === 'local' && (
          <div className="space-y-1.5">
            <Label htmlFor="backup-local-path" className="text-xs">
              {t('admin.settings.backupLocalPath')}
            </Label>
            <Input
              id="backup-local-path"
              value={localPath}
              onChange={(e) => setLocalPath(e.target.value)}
              className="h-9 rounded-lg"
            />
          </div>
        )}
        <div className="space-y-1.5">
          <Label htmlFor="backup-encryption-key" className="text-xs">
            {t('admin.settings.backupEncryptionKey')}
            {initial.backup_encryption_key_set && (
              <span className="ml-2 text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                {t('admin.settings.backupKeyConfigured')}
              </span>
            )}
          </Label>
          <Input
            id="backup-encryption-key"
            type="password"
            value={encryptionKey}
            onChange={(e) => setEncryptionKey(e.target.value)}
            placeholder={t('admin.settings.backupKeyPlaceholder')}
            autoComplete="off"
            className="h-9 rounded-lg"
          />
        </div>
      </div>

      {provider === 's3' && (
        <div className="space-y-4 rounded-lg border border-border/40 p-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="backup-s3-bucket" className="text-xs">
                {t('admin.settings.backupS3Bucket')}
              </Label>
              <Input
                id="backup-s3-bucket"
                value={s3Bucket}
                onChange={(e) => setS3Bucket(e.target.value)}
                autoComplete="off"
                className="h-9 rounded-lg"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="backup-s3-region" className="text-xs">
                {t('admin.settings.backupS3Region')}
              </Label>
              <Input
                id="backup-s3-region"
                value={s3Region}
                onChange={(e) => setS3Region(e.target.value)}
                autoComplete="off"
                className="h-9 rounded-lg"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="backup-s3-endpoint" className="text-xs">
                {t('admin.settings.backupS3Endpoint')}
              </Label>
              <Input
                id="backup-s3-endpoint"
                value={s3Endpoint}
                onChange={(e) => setS3Endpoint(e.target.value)}
                placeholder="https://..."
                autoComplete="off"
                className="h-9 rounded-lg"
              />
            </div>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="space-y-1.5">
              <Label htmlFor="backup-s3-access-key" className="text-xs">
                {t('admin.settings.backupS3AccessKey')}
                {initial.storage_s3_access_key_set && (
                  <span className="ml-2 text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                    {t('admin.settings.backupKeyConfigured')}
                  </span>
                )}
              </Label>
              <Input
                id="backup-s3-access-key"
                type="password"
                value={s3AccessKey}
                onChange={(e) => setS3AccessKey(e.target.value)}
                placeholder={t('admin.settings.backupSecretPlaceholder')}
                autoComplete="off"
                className="h-9 rounded-lg"
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="backup-s3-secret-key" className="text-xs">
                {t('admin.settings.backupS3SecretKey')}
                {initial.storage_s3_secret_key_set && (
                  <span className="ml-2 text-[10px] font-medium text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                    {t('admin.settings.backupKeyConfigured')}
                  </span>
                )}
              </Label>
              <Input
                id="backup-s3-secret-key"
                type="password"
                value={s3SecretKey}
                onChange={(e) => setS3SecretKey(e.target.value)}
                placeholder={t('admin.settings.backupSecretPlaceholder')}
                autoComplete="off"
                className="h-9 rounded-lg"
              />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3">
            <Button
              type="button"
              variant="outline"
              onClick={() => testMutation.mutate()}
              disabled={testMutation.isPending}
            >
              <PlugZap size={14} />
              {testMutation.isPending ? t('common.loading') : t('admin.settings.backupTestS3')}
            </Button>
            {testResult && (
              <p
                role="status"
                className={`flex items-center gap-1.5 text-xs ${testResult.success ? 'text-emerald-600' : 'text-destructive'}`}
              >
                {testResult.success ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
                {testResult.success
                  ? t('admin.settings.backupTestSuccess')
                  : testResult.error || t('admin.settings.backupTestFailed')}
              </p>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          <Save size={13} />
          {saveMutation.isPending ? t('common.loading') : t('common.save')}
        </Button>
        <Button
          type="button"
          variant="outline"
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending}
        >
          <Play size={13} />
          {runMutation.isPending ? t('common.loading') : t('admin.settings.backupRunNow')}
        </Button>
      </div>
    </div>
  )
}
