import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { toast } from 'sonner'
import { documents, type DocumentFormat, type DocumentKind, type DocumentPeriod } from '@/lib/api'
import { extractApiError } from '@/lib/api-errors'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { DateRangePicker } from '@/components/ui/date-range-picker'

const REPORT_SECTIONS = [
  'net_worth',
  'income_expenses',
  'account_balances',
  'large_transactions',
  'recurring_obligations',
] as const

const PLAN_SECTIONS = [
  'goals',
  'budgets',
  'recurring_forecast',
  'savings_suggestion',
] as const

const SECTION_KEYS: Record<DocumentKind, readonly string[]> = {
  report: REPORT_SECTIONS,
  plan: PLAN_SECTIONS,
}

const SECTION_I18N: Record<string, string> = {
  net_worth: 'documents.sectionNetWorth',
  income_expenses: 'documents.sectionIncomeExpenses',
  account_balances: 'documents.sectionAccountBalances',
  large_transactions: 'documents.sectionLargeTransactions',
  recurring_obligations: 'documents.sectionRecurringObligations',
  goals: 'documents.sectionGoals',
  budgets: 'documents.sectionBudgets',
  recurring_forecast: 'documents.sectionRecurringForecast',
  savings_suggestion: 'documents.sectionSavingsSuggestion',
}

const PERIODS: readonly DocumentPeriod[] = ['last_month', 'last_quarter', 'ytd', 'custom']

interface DocumentDialogProps {
  open: boolean
  onClose: () => void
}

/**
 * Collects the options for a downloadable document and asks the server for
 * it. The section set changes with the document type, so switching type
 * resets the selection to that type's full set rather than carrying over
 * keys that would be rejected.
 */
export function DocumentDialog({ open, onClose }: DocumentDialogProps) {
  const { t } = useTranslation()
  const [kind, setKind] = useState<DocumentKind>('report')
  const [format, setFormat] = useState<DocumentFormat>('pdf')
  const [period, setPeriod] = useState<DocumentPeriod>('last_quarter')
  const [customFrom, setCustomFrom] = useState('')
  const [customTo, setCustomTo] = useState('')
  const [sections, setSections] = useState<string[]>([...REPORT_SECTIONS])
  const [title, setTitle] = useState('')
  const [subtitle, setSubtitle] = useState('')
  const [currency, setCurrency] = useState('')
  const [downloading, setDownloading] = useState(false)
  const [error, setError] = useState('')

  const reset = () => {
    setKind('report')
    setFormat('pdf')
    setPeriod('last_quarter')
    setCustomFrom('')
    setCustomTo('')
    setSections([...REPORT_SECTIONS])
    setTitle('')
    setSubtitle('')
    setCurrency('')
    setError('')
  }

  const handleClose = () => {
    reset()
    onClose()
  }

  const handleKindChange = (next: DocumentKind) => {
    setKind(next)
    setSections([...SECTION_KEYS[next]])
  }

  const toggleSection = (key: string) => {
    setSections((current) =>
      current.includes(key) ? current.filter((k) => k !== key) : [...current, key],
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')

    if (sections.length === 0) {
      setError(t('documents.noSections'))
      return
    }
    if (period === 'custom' && (!customFrom || !customTo)) {
      setError(t('documents.customRangeRequired'))
      return
    }

    setDownloading(true)
    try {
      await documents.download(kind, {
        format,
        period,
        ...(period === 'custom' ? { start_date: customFrom, end_date: customTo } : {}),
        sections,
        ...(title ? { title } : {}),
        ...(subtitle ? { subtitle } : {}),
        ...(currency ? { currency: currency.toUpperCase() } : {}),
      })
      toast.success(t('documents.success'))
      handleClose()
    } catch (err) {
      toast.error(extractApiError(err, t('documents.error')))
    } finally {
      setDownloading(false)
    }
  }

  const pickerButton = (active: boolean) =>
    `px-3 py-1.5 text-xs font-semibold transition-colors rounded-md ${
      active
        ? 'bg-primary text-primary-foreground'
        : 'text-muted-foreground hover:text-foreground hover:bg-muted/50'
    }`

  return (
    <Dialog open={open} onOpenChange={(v) => !v && handleClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t('documents.dialogTitle')}</DialogTitle>
          <DialogDescription>{t('documents.dialogDescription')}</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label>{t('documents.typeLabel')}</Label>
              <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1">
                <button type="button" className={pickerButton(kind === 'report')} onClick={() => handleKindChange('report')}>
                  {t('documents.typeReport')}
                </button>
                <button type="button" className={pickerButton(kind === 'plan')} onClick={() => handleKindChange('plan')}>
                  {t('documents.typePlan')}
                </button>
              </div>
            </div>
            <div className="space-y-2">
              <Label>{t('documents.formatLabel')}</Label>
              <div className="flex items-center gap-1 rounded-lg border border-border bg-card p-1">
                <button type="button" className={pickerButton(format === 'pdf')} onClick={() => setFormat('pdf')}>
                  PDF
                </button>
                <button type="button" className={pickerButton(format === 'html')} onClick={() => setFormat('html')}>
                  HTML
                </button>
              </div>
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t('documents.periodLabel')}</Label>
            <div className="flex flex-wrap items-center gap-1 rounded-lg border border-border bg-card p-1">
              {PERIODS.map((key) => (
                <button
                  key={key}
                  type="button"
                  className={pickerButton(period === key)}
                  onClick={() => setPeriod(key)}
                >
                  {t(`documents.period_${key}`)}
                </button>
              ))}
              {period === 'custom' && (
                <DateRangePicker
                  variant="button"
                  from={customFrom}
                  to={customTo}
                  disallowFuture
                  maxRangeYears={10}
                  onChange={(f, to) => {
                    setCustomFrom(f)
                    setCustomTo(to)
                  }}
                  label={t('documents.period_custom')}
                />
              )}
            </div>
          </div>

          <div className="space-y-2">
            <Label>{t('documents.sectionsLabel')}</Label>
            <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
              {SECTION_KEYS[kind].map((key) => (
                <label key={key} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={sections.includes(key)}
                    onChange={() => toggleSection(key)}
                    className="rounded border-border"
                  />
                  {t(SECTION_I18N[key])}
                </label>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="doc-title">{t('documents.titleLabel')}</Label>
              <Input
                id="doc-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder={t('documents.titlePlaceholder')}
                maxLength={120}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="doc-currency">{t('documents.currencyLabel')}</Label>
              <Input
                id="doc-currency"
                value={currency}
                onChange={(e) => setCurrency(e.target.value.toUpperCase())}
                placeholder={t('documents.currencyPlaceholder')}
                maxLength={3}
              />
            </div>
          </div>
          <div className="space-y-2">
            <Label htmlFor="doc-subtitle">{t('documents.subtitleLabel')}</Label>
            <Input
              id="doc-subtitle"
              value={subtitle}
              onChange={(e) => setSubtitle(e.target.value)}
              placeholder={t('documents.subtitlePlaceholder')}
              maxLength={200}
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={handleClose}>
              {t('common.cancel')}
            </Button>
            <Button type="submit" disabled={downloading}>
              {downloading ? t('documents.generating') : t('documents.generate')}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
