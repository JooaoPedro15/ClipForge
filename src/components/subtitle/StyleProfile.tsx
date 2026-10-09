import { X } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { PROFILE_LABELS, describeTiming, formatF1, getProfileStatus } from '@/lib/styleFormat'
import { cn } from '@/lib/utils'
import type { StyleLibrary, StyleProfileName, StyleReport } from '@/types/subtitleStyle'

// Resultado do ultimo ensino.
export function StyleReportBox({ report }: { report: StyleReport }) {
  return (
    <div className="space-y-1.5 rounded-md border border-line bg-app px-3 py-2.5 text-xs text-text-secondary">
      <p className="text-[13px] font-medium text-text-primary">Aprendido no perfil {PROFILE_LABELS[report.profile]}</p>
      <p>
        Acerto de quebra antes: <span className="text-text-primary">{formatF1(report.f1Before)}</span>, fórmula padrão:{' '}
        {formatF1(report.f1Formula)}, depois (neste vídeo): <span className="text-text-primary">{formatF1(report.f1After)}</span>
      </p>
      <p className="text-text-muted">
        {report.gapExamples} espaços entre palavras e {report.timingSamples} legendas com tempo aproveitados.
      </p>
      {report.warnings.map((warning) => (
        <p className="text-status-warn" key={warning}>
          {warning}
        </p>
      ))}
    </div>
  )
}

interface StyleProfileProps {
  profile: StyleProfileName
  library: StyleLibrary | null
  busy: boolean
  onForget: (videoId: string) => void
}

// Um perfil (vertical ou horizontal): quantos videos faltam e o que ele ja aprendeu.
export function StyleProfile({ profile, library, busy, onForget }: StyleProfileProps) {
  const status = getProfileStatus(library, profile)
  const minVideos = library?.minVideos ?? 3
  const summary = library?.profiles[profile]
  const videos = library?.videos.filter((video) => video.profile === profile) ?? []

  return (
    <div className="space-y-2 rounded-md border border-line bg-app px-3 py-2.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[13px] font-medium text-text-primary">{PROFILE_LABELS[profile]}</span>
        <span className={cn('text-xs', status.active ? 'text-status-green' : 'text-text-muted')}>
          {status.active ? 'Ativo' : status.remaining === 1 ? 'Falta 1 vídeo' : `Faltam ${status.remaining} vídeos`}
        </span>
      </div>

      {/* Um traco por video ensinado ate o minimo: da pra ver o quanto falta de longe. */}
      <div aria-label={`${status.videos} de ${minVideos} vídeos`} className="flex gap-1" role="img">
        {Array.from({ length: Math.max(minVideos, status.videos) }, (_, index) => (
          <span
            className={cn('h-1 flex-1 rounded-full', index < status.videos ? 'bg-text-primary' : 'bg-raised')}
            key={index}
          />
        ))}
      </div>

      {summary || videos.length > 0 ? (
        <details className="group text-xs">
          <summary className="cursor-pointer text-text-muted hover:text-text-secondary">
            {videos.length} {videos.length === 1 ? 'vídeo ensinado' : 'vídeos ensinados'}
          </summary>
          <div className="mt-2 space-y-2">
            {summary ? <p className="text-text-secondary">{describeTiming(summary.params)}</p> : null}
            {summary?.tree ? (
              <pre className="max-h-48 overflow-auto rounded bg-black/40 p-2 font-mono text-[11px] leading-5 text-text-secondary">
                {summary.tree}
              </pre>
            ) : null}
            <ul className="divide-y divide-line">
              {videos.map((video) => (
                <li className="flex items-center justify-between gap-2 py-1.5" key={video.id}>
                  <span className="min-w-0">
                    <span className="block truncate text-text-primary">{video.name}</span>
                    <span className="block text-text-muted">acerto antes: {formatF1(video.f1Before)}</span>
                  </span>
                  <Button
                    aria-label={`Remover ${video.name}`}
                    disabled={busy}
                    leadingIcon={<X className="h-3.5 w-3.5" />}
                    onClick={() => onForget(video.id)}
                    size="sm"
                    variant="quiet"
                  >
                    Remover
                  </Button>
                </li>
              ))}
            </ul>
          </div>
        </details>
      ) : null}
    </div>
  )
}
