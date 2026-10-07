import { FolderOpen, ListChecks, LoaderCircle, TriangleAlert, X } from 'lucide-react'
import { useState } from 'react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { useSubtitleStyle } from '@/hooks/useSubtitleStyle'
import { PROFILE_LABELS, describeTiming, formatF1, getProfileStatus } from '@/lib/styleFormat'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type { StyleLibrary, StyleProfileName, StyleReport } from '@/types/subtitleStyle'

type PickKind = 'original' | 'srt' | 'final'

const VIDEO_FILTERS = [{ name: 'Vídeo', extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm'] }]
const SRT_FILTERS = [{ name: 'Legenda', extensions: ['srt'] }]
const PROFILES: StyleProfileName[] = ['vertical', 'horizontal']
const PICKERS: Array<{ kind: PickKind; label: string; hint: string }> = [
  { kind: 'original', label: 'Vídeo original', hint: 'o mesmo que o app legendou' },
  { kind: 'srt', label: 'SRT corrigido', hint: 'exportado do Premiere' },
  { kind: 'final', label: 'Vídeo final', hint: 'já com os seus cortes' },
]

function ReportBox({ report }: { report: StyleReport }) {
  return (
    <div className="space-y-2 rounded-xl border border-white/8 bg-black/20 px-4 py-3 text-sm text-text-secondary">
      <p className="font-medium text-text-primary">Aprendido — {PROFILE_LABELS[report.profile]}</p>
      <p>
        Acerto de quebra antes: <span className="text-text-primary">{formatF1(report.f1Before)}</span> · fórmula padrão:{' '}
        {formatF1(report.f1Formula)} · depois (neste vídeo): {formatF1(report.f1After)}
      </p>
      <p className="text-xs text-text-muted">
        {report.gapExamples} espaços entre palavras e {report.timingSamples} legendas com tempo aproveitados.
      </p>
      {report.warnings.map((warning) => (
        <p className="text-xs text-status-yellow" key={warning}>
          {warning}
        </p>
      ))}
    </div>
  )
}

function ProfileBox({
  profile,
  library,
  busy,
  onForget,
}: {
  profile: StyleProfileName
  library: StyleLibrary | null
  busy: boolean
  onForget: (videoId: string) => void
}) {
  const status = getProfileStatus(library, profile)
  const summary = library?.profiles[profile]
  const videos = library?.videos.filter((video) => video.profile === profile) ?? []

  return (
    <div className="space-y-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium text-text-primary">{PROFILE_LABELS[profile]}</span>
        <Badge tone={status.active ? 'green' : 'neutral'}>
          {status.active ? `Ativo · ${status.videos} vídeos` : `${status.videos}/${library?.minVideos ?? 3} vídeos`}
        </Badge>
      </div>

      {!status.active ? (
        <p className="text-xs text-text-muted">
          Falta{status.remaining === 1 ? '' : 'm'} {status.remaining} vídeo{status.remaining === 1 ? '' : 's'} pra geração usar este estilo.
        </p>
      ) : null}

      {summary ? <p className="text-xs text-text-muted">{describeTiming(summary.params)}</p> : null}

      {summary?.tree ? (
        <details>
          <summary className="cursor-pointer text-xs text-text-muted">Ver a árvore (as suas regras de quebra)</summary>
          <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-black/30 p-3 font-mono text-[11px] leading-5 text-text-secondary">
            {summary.tree}
          </pre>
        </details>
      ) : null}

      {videos.length > 0 ? (
        <ul className="divide-y divide-white/6">
          {videos.map((video) => (
            <li className="flex items-center justify-between gap-3 py-2" key={video.id}>
              <span className="min-w-0">
                <span className="block truncate text-text-primary">{video.name}</span>
                <span className="block text-xs text-text-muted">
                  acerto antes: {formatF1(video.f1Before)} · fórmula padrão: {formatF1(video.f1Formula)}
                </span>
              </span>
              <Button
                aria-label={`Remover ${video.name}`}
                disabled={busy}
                leadingIcon={<X className="h-4 w-4" />}
                onClick={() => onForget(video.id)}
                variant="ghost"
              >
                Remover
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  )
}

// Painel "Meu estilo": ensina o app com um video que o usuario corrigiu no Premiere.
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

  return (
    <Card className="space-y-5">
      <div className="flex items-center gap-3">
        <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/8 text-white">
          <ListChecks className="h-5 w-5" />
        </div>
        <div>
          <h3 className="text-xl font-semibold text-text-primary">Meu estilo</h3>
          <p className="mt-1 text-sm text-text-secondary">Ensine com um vídeo que você corrigiu no Premiere.</p>
        </div>
      </div>

      <div className="grid gap-2">
        {PICKERS.map((picker) => {
          const chosen = paths[picker.kind]
          return (
            <button
              className="app-no-drag flex items-center justify-between gap-3 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-left text-sm text-text-secondary transition hover:border-white/20"
              key={picker.kind}
              onClick={() => void pick(picker.kind)}
              type="button"
            >
              <span className="font-medium text-text-primary">{picker.label}</span>
              <span className="truncate font-mono text-xs text-text-muted">{chosen ? getFileName(chosen) : picker.hint}</span>
            </button>
          )
        })}
      </div>

      <Button
        disabled={!ready}
        leadingIcon={style.running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : <FolderOpen className="h-4 w-4" />}
        onClick={() => void teach()}
      >
        {style.running ? 'Ensinando...' : 'Ensinar'}
      </Button>

      {style.running && style.progress ? <p className="text-sm text-text-secondary">{style.progress.message}</p> : null}
      {style.error ? (
        <p className="flex items-start gap-2 text-sm text-status-red">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" />
          {style.error}
        </p>
      ) : null}
      {style.report ? <ReportBox report={style.report} /> : null}

      {PROFILES.map((profile) => (
        <ProfileBox
          busy={style.running}
          key={profile}
          library={style.library}
          onForget={(videoId) => void style.forget(videoId)}
          profile={profile}
        />
      ))}
    </Card>
  )
}
