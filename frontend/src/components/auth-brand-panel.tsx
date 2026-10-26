import { useTranslation } from 'react-i18next'
import { ShellLogo } from '@/components/shell-logo'

// Left-hand brand panel for the auth/onboarding screens. A near-black void
// field with a static starfield behind an oversized, translucent Quad4 mark.
// Decorative only, hidden below lg where the form takes the full width and
// carries its own compact header.
export function AuthBrandPanel() {
  const { t } = useTranslation()

  return (
    <div className="relative hidden overflow-hidden border-r border-[#1f1f24] bg-[#0a0a0b] p-12 text-white lg:flex lg:flex-col lg:justify-between">
      {/* Static starfield */}
      <div aria-hidden className="quad4-starfield" />

      {/* Oversized translucent mark, bleeding off the lower-right edge */}
      <div
        aria-hidden
        className="pointer-events-none absolute -right-28 -bottom-24 text-white/[0.05]"
        style={{ transform: 'rotate(-8deg)' }}
      >
        <ShellLogo size={640} />
      </div>

      {/* Depth: gentle vignette toward the edges */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            'radial-gradient(115% 90% at 78% 8%, transparent 42%, rgba(0, 0, 0, 0.5) 100%)',
        }}
      />

      {/* Wordmark lockup */}
      <div className="relative flex items-center gap-3.5">
        <div className="flex h-9 w-9 items-center justify-center rounded-md border border-[#2a2a31] bg-[#0d0d10]">
          <ShellLogo size={18} className="text-white" />
        </div>
        <span className="font-mono text-sm font-bold tracking-[0.3em] text-white">
          QUAD4 FINANCE
        </span>
      </div>

      {/* Tagline */}
      <div className="relative max-w-md space-y-5">
        <h2 className="text-[2.6rem] font-medium leading-[1.08] tracking-tight text-white">
          {t('setup.brandTagline')}
        </h2>
        <p className="max-w-sm text-base leading-relaxed text-white/60">
          {t('setup.brandSubtitle')}
        </p>
        <div className="flex items-center gap-2.5 pt-1 font-mono text-xs tracking-[0.12em] text-white/50">
          <span>{t('setup.brandOpen')}</span>
          <span className="h-1 w-1 rounded-full bg-white/35" />
          <span>{t('setup.brandSelfHosted')}</span>
          <span className="h-1 w-1 rounded-full bg-white/35" />
          <span>{t('setup.brandPrivate')}</span>
        </div>
      </div>
    </div>
  )
}
