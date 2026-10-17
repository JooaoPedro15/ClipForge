import { FileCode2, FolderSearch, GraduationCap, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { FieldRow, StackedField } from '@/components/inspector/fields'
import { InspectorSection } from '@/components/inspector/InspectorSection'
import { Button } from '@/components/ui/Button'
import { NumberStepper } from '@/components/ui/NumberStepper'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import type { PreeditActionResult } from '@/hooks/usePreedit'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type { PreeditZoomStyle } from '@/types/preedit'

interface PreeditInspectorProps {
  onPickMolde: () => void
  onClearMolde: () => void
  onTeachProjects: () => Promise<PreeditActionResult>
  onTeachFinals: () => Promise<PreeditActionResult>
}

function counts(longo: number, short: number): string {
  return `${longo} ${longo === 1 ? 'longo' : 'longos'} · ${short} Shorts`
}

const zoomOptions: Array<{ value: PreeditZoomStyle; label: string }> = [
  { value: 'aproximando', label: 'Aproximando' },
  { value: 'seco', label: 'Seco' },
]

// Inspetor da Pre-edicao que aprende: o tamanho do video, o zoom, o molde e o que o app ja aprendeu.
export function PreeditInspector({ onPickMolde, onClearMolde, onTeachProjects, onTeachFinals }: PreeditInspectorProps) {
  const settings = useAppStore((state) => state.preeditSettings)
  const patchSettings = useAppStore((state) => state.patchPreeditSettings)
  const library = useAppStore((state) => state.preeditLibrary)
  const [message, setMessage] = useState<string | null>(null)
  const moldeName = settings.moldePath ? getFileName(settings.moldePath) : null

  async function run(action: () => Promise<PreeditActionResult>) {
    setMessage((await action()).message)
  }

  return (
    <div className="pb-6">
      <InspectorSection defaultOpen summary={`${settings.minutes} min · ${settings.zoomStyle}`} title="Vídeo longo">
        <FieldRow hint="Mais ou menos quanto o vídeo final dura" label="Duração (min)">
          <NumberStepper label="duração em minutos" max={180} min={1} onChange={(minutes) => patchSettings({ minutes })} value={settings.minutes} />
        </FieldRow>
        <StackedField
          hint={settings.zoomStyle === 'aproximando' ? 'Entra no rosto e continua chegando perto, devagar, até o corte.' : 'Zoom parado no rosto.'}
          label="Zoom"
        >
          <SegmentedControl label="estilo do zoom" onChange={(zoomStyle) => patchSettings({ zoomStyle })} options={zoomOptions} value={settings.zoomStyle} />
        </StackedField>
      </InspectorSection>

      <InspectorSection defaultOpen summary={moldeName ?? 'sem molde'} title="Molde">
        <div className="flex items-center gap-2">
          <FileCode2 className="h-4 w-4 shrink-0 text-text-muted" />
          <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-primary" title={settings.moldePath || undefined}>
            {moldeName ?? 'Sem molde'}
          </span>
          {moldeName ? (
            <Button onClick={onClearMolde} size="sm" variant="quiet">
              Remover
            </Button>
          ) : null}
          <Button onClick={onPickMolde} size="sm" variant="ghost">
            {moldeName ? 'Trocar' : 'Escolher XML'}
          </Button>
        </div>
        <p className="text-xs leading-snug text-text-muted">
          Sem molde, a sequência sai do tamanho da gravação e sem zoom. Pra zoom no rosto, exporte um vídeo seu com um clipe com zoom em Arquivo › Exportar ›
          Final Cut Pro XML.
        </p>
      </InspectorSection>

      <InspectorSection defaultOpen summary={library ? `${library.recordings.longo + library.finals.longo} longos` : '...'} title="Aprendizado">
        {library ? (
          <dl className="space-y-1 text-xs">
            <div className="flex justify-between gap-3">
              <dt className="text-text-muted">Com bruto (cortes e zoom)</dt>
              <dd className="font-mono text-text-primary tabular-nums">
                {counts(library.recordings.longo, library.recordings.short)}
              </dd>
            </div>
            <div className="flex justify-between gap-3">
              <dt className="text-text-muted">Vídeos prontos (só zoom)</dt>
              <dd className="font-mono text-text-primary tabular-nums">
                {counts(library.finals.longo, library.finals.short)}
              </dd>
            </div>
          </dl>
        ) : (
          <p className="text-xs text-text-muted">Lendo a biblioteca...</p>
        )}
        {library && !library.editorReady ? (
          <p className="flex items-start gap-1.5 text-xs text-status-warn">
            <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
            Ensine pelo menos 3 gravações de vídeo longo com bruto antes de gerar.
          </p>
        ) : null}
        <div className="flex flex-wrap gap-2">
          <Button leadingIcon={<GraduationCap className="h-4 w-4" />} onClick={() => void run(onTeachProjects)} size="sm" variant="ghost">
            Ensinar com projetos
          </Button>
          <Button leadingIcon={<FolderSearch className="h-4 w-4" />} onClick={() => void run(onTeachFinals)} size="sm" variant="ghost">
            Ensinar com vídeos prontos
          </Button>
        </div>
        <p className="text-xs leading-snug text-text-muted">
          Projetos: os .prproj de vídeos com o bruto (ensina cortes e zoom). Vídeos prontos: escolha a pasta dos projetos e depois a dos vídeos exportados (ensina
          só zoom). Corrigiu um XML no Premiere? Ensine com esse projeto.
        </p>
        {message ? <p className="text-xs text-status-warn">{message}</p> : null}
      </InspectorSection>
    </div>
  )
}
