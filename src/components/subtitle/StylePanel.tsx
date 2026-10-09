import { Check, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { InspectorSection } from '@/components/inspector/InspectorSection'
import { StyleProfile, StyleReportBox } from '@/components/subtitle/StyleProfile'
import { Button } from '@/components/ui/Button'
import { useSubtitleStyle } from '@/hooks/useSubtitleStyle'
import { getProfileStatus } from '@/lib/styleFormat'
import { cn, getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type { StyleProfileName } from '@/types/subtitleStyle'

type PickKind = 'original' | 'srt' | 'final'

const VIDEO_FILTERS = [{ name: 'Vídeo', extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm'] }]
const SRT_FILTERS = [{ name: 'Legenda', extensions: ['srt'] }]
const PROFILES: StyleProfileName[] = ['vertical', 'horizontal']
// A ordem e a do fluxo real: legenda no app, corrige no Premiere, exporta o final.
const PICKERS: Array<{ kind: PickKind; label: string; hint: string }> = [
  { kind: 'original', label: 'Vídeo original', hint: 'o mesmo que o app legendou' },
  { kind: 'srt', label: 'SRT corrigido', hint: 'exportado do Premiere' },
  { kind: 'final', label: 'Vídeo final', hint: 'já com os seus cortes' },
]

// Secao "Meu estilo" do Inspetor: ensina o app com um video que o usuario corrigiu no Premiere.
export function StylePanel() {
  const style = useSubtitleStyle()
  const settings = useAppStore((state) => state.subtitleSettings)
  const [paths, setPaths] = useState<Record<PickKind, string | null>>({ original: null, srt: null, final: null })

  if (!style.available) {
    return null
  }

  async function pick(kind: PickKind) {
    const selected = await window.clipforge.dialog.openFiles(kind === 'srt' ? SRT_FILTERS : VIDEO_FILTERS)
    const first = selected[0]
    if (first) {
      setPaths((current) => ({ ...current, [kind]: first }))
    }
  }

  async function teach() {
    if (!paths.original || !paths.srt || !paths.final) {
      return
    }
    await style.learn({
      originalPath: paths.original,
      srtPath: paths.srt,
      finalPath: paths.final,
      model: settings.model,
      language: settings.language,
      useCpu: settings.useCpu,
    })
  }

  const ready = Boolean(paths.original && paths.srt && paths.final) && !style.running
  const activeProfiles = PROFILES.filter((profile) => getProfileStatus(style.library, profile).active)
  const summary =
    activeProfiles.length === 0 ? 'Nenhum perfil ativo' : activeProfiles.length === 1 ? '1 perfil ativo' : '2 perfis ativos'

  return (
    <InspectorSection summary={summary} title="Meu estilo">
      <p className="text-xs leading-snug text-text-muted">
        Ensine com um vídeo que você corrigiu no Premiere. O app aprende onde você quebra as legendas.
      </p>

      <ol className="space-y-1.5">
        {PICKERS.map((picker, index) => {
          const chosen = paths[picker.kind]
          return (
            <li key={picker.kind}>
              <button
                className="app-no-drag flex w-full items-center gap-3 rounded-md border border-line bg-raised px-3 py-2 text-left transition-colors hover:border-line-strong"
                onClick={() => void pick(picker.kind)}
                type="button"
              >
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    chosen ? 'bg-text-primary text-black' : 'border border-line-strong text-text-muted',
                  )}
                >
                  {chosen ? <Check className="h-3 w-3" /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-text-primary">{picker.label}</span>
                  <span className={cn('block truncate text-xs', chosen ? 'font-mono text-text-secondary' : 'text-text-muted')}>
                    {chosen ? getFileName(chosen) : picker.hint}
                  </span>
                </span>
              </button>
            </li>
          )
        })}
      </ol>

      <Button
        className="w-full"
        disabled={!ready}
        leadingIcon={style.running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
        onClick={() => void teach()}
        size="sm"
      >
        {style.running ? 'Ensinando…' : 'Ensinar'}
      </Button>

      {style.running && style.progress ? <p className="text-xs text-text-secondary">{style.progress.message}</p> : null}
      {style.error ? (
        <p className="flex items-start gap-2 text-xs text-status-red">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {style.error}
        </p>
      ) : null}
      {style.report ? <StyleReportBox report={style.report} /> : null}

      {PROFILES.map((profile) => (
        <StyleProfile
          busy={style.running}
          key={profile}
          library={style.library}
          onForget={(videoId) => void style.forget(videoId)}
          profile={profile}
        />
      ))}
    </InspectorSection>
  )
}
