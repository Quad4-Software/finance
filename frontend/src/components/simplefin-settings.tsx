import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Landmark, Save } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import {
  admin,
  type SimplefinSettings as SimplefinSettingsData,
  type SimplefinSettingsUpdate,
} from '@/lib/api'

export function SimplefinSettings() {
  const { t } = useTranslation()
  const settingsQuery = useQuery({
    queryKey: ['admin', 'simplefin-settings'],
    queryFn: admin.simplefinSettings,
  })
  const setting = settingsQuery.data

  return (
    <section className="mb-8 rounded-xl border border-border/60 bg-card overflow-hidden">
      <div className="px-5 py-4 border-b border-border/40">
        <div className="flex items-center gap-2 mb-0.5">
          <Landmark size={15} className="text-muted-foreground" />
          <h2 className="text-sm font-semibold text-foreground">
            {t('admin.settings.simplefinTitle')}
          </h2>
        </div>
        <p className="text-xs text-muted-foreground">{t('admin.settings.simplefinSubtitle')}</p>
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
        <SimplefinSettingsForm key={JSON.stringify(setting)} initial={setting} />
      )}
    </section>
  )
}

function SimplefinSettingsForm({ initial }: { initial: SimplefinSettingsData }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()

  const [enabled, setEnabled] = useState(initial.simplefin_enabled)
  const [apiUrl, setApiUrl] = useState(initial.simplefin_api_url)

  const saveMutation = useMutation({
    mutationFn: () => {
      const payload: SimplefinSettingsUpdate = {
        simplefin_enabled: enabled,
        simplefin_api_url: apiUrl,
      }
      return admin.updateSimplefinSettings(payload)
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'simplefin-settings'] })
      // The provider list reads the same effective flag.
      queryClient.invalidateQueries({ queryKey: ['connections', 'providers'] })
      toast.success(t('admin.settings.updated'))
    },
    onError: () => toast.error(t('common.error')),
  })

  return (
    <div className="p-5 space-y-5">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-1">
          <Label id="simplefin-enabled-label" className="text-xs">
            {t('admin.settings.simplefinEnabled')}
          </Label>
          <p className="text-xs text-muted-foreground">
            {t('admin.settings.simplefinEnabledHint')}
          </p>
        </div>
        <Switch
          checked={enabled}
          onCheckedChange={setEnabled}
          aria-labelledby="simplefin-enabled-label"
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="simplefin-api-url" className="text-xs">
          {t('admin.settings.simplefinApiUrl')}
        </Label>
        <Input
          id="simplefin-api-url"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          placeholder="https://bridge.simplefin.org"
          autoComplete="off"
          className="h-9 rounded-lg"
        />
        <p className="text-xs text-muted-foreground">
          {t('admin.settings.simplefinApiUrlHint')}
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => saveMutation.mutate()} disabled={saveMutation.isPending}>
          <Save size={13} />
          {saveMutation.isPending ? t('common.loading') : t('common.save')}
        </Button>
      </div>
    </div>
  )
}
