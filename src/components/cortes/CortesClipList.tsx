import { FileCode2, FolderOpen, RotateCcw } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { NumberStepper } from '@/components/ui/NumberStepper'
import { formatClock, sameDurations, topClips } from '@/lib/cortesClips'
import { formatDuration, getFileName } from '@/lib/utils'
import type { CortesAnalysisSummary, CortesDurations, CortesXmlState } from '@/types/cortes'

interface CortesClipListProps {
  analysis: CortesAnalysisSummary
  xml: CortesXmlState | null
  templatePath: string
  // Duracoes atuais do Inspetor: se mudaram desde a analise, aparece "Refazer clipes".
  durations: CortesDurations
  onGenerateXml: (clips: number[]) => void
  onOpenPath: (path: string) => void
  onResegment: () => void
}

const pad = (value: number) => String(value).padStart(2, '0')

// Clipes de um react analisado: marcar quais vao pro XML e gerar.
export function CortesClipList({ analysis, xml, templatePath, durations, onGenerateXml, onOpenPath, onResegment }: CortesClipListProps) {
  const { clips } = analysis
  // A lista comeca toda marcada; o item recria este componente quando a lista muda.
  const [selected, setSelected] = useState<Set<number>>(() => new Set(clips.map((clip) => clip.n)))
  const [best, setBest] = useState(Math.min(5, Math.max(1, clips.length)))

  const allSelected = selected.size === clips.length
  const hasTemplate = templatePath !== ''
  const generating = xml?.status === 'running'
  const durationsChanged = !sameDurations(analysis.durations, durations)

  function toggle(n: number) {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(n)) {
        next.delete(n)
      } else {
        next.add(n)
      }
      return next
    })
  }

  return (
    <div className="mt-3 overflow-hidden rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line bg-raised/40 px-3 py-2">
        <Button onClick={() => setSelected(allSelected ? new Set() : new Set(clips.map((clip) => clip.n)))} size="sm" variant="ghost">
          {allSelected ? 'Nenhum' : 'Todos'}
        </Button>
        <NumberStepper label="quantos clipes de maior nota" max={clips.length} min={1} onChange={setBest} value={best} />
        <Button onClick={() => setSelected(new Set(topClips(clips, best)))} size="sm" variant="ghost">
          Marcar {best} melhores
        </Button>
        <span className="ml-auto text-xs text-text-muted tabular-nums">
          {selected.size} de {clips.length} marcados
        </span>
      </div>

      <ul className="max-h-[340px] divide-y divide-line overflow-y-auto">
        {clips.map((clip) => (
          <li key={clip.n}>
            <label className="flex cursor-pointer items-center gap-3 px-3 py-2 text-[13px] transition-colors hover:bg-raised/50">
              <input checked={selected.has(clip.n)} className="app-no-drag h-3.5 w-3.5 shrink-0 accent-accent" onChange={() => toggle(clip.n)} type="checkbox" />
              <span className="w-5 shrink-0 font-mono text-xs text-text-muted tabular-nums">{pad(clip.n)}</span>
              <span className="w-14 shrink-0 font-mono text-xs text-text-secondary tabular-nums">{formatClock(clip.start)}</span>
              <span className="w-14 shrink-0 font-mono text-xs text-text-secondary tabular-nums">{formatDuration(clip.end - clip.start)}</span>
              <span className="min-w-0 flex-1 truncate text-text-primary" title={clip.title}>
                {clip.title}
              </span>
              <span className="w-9 shrink-0 text-right font-mono text-xs text-text-secondary tabular-nums" title="Nota de gancho (0 a 10)">
                {clip.score === null ? '–' : clip.score.toFixed(1)}
              </span>
            </label>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-1 border-t border-line px-3 py-2">
        <Button
          disabled={!hasTemplate || selected.size === 0 || generating}
          leadingIcon={<FileCode2 className="h-3.5 w-3.5" />}
          onClick={() => onGenerateXml([...selected].sort((a, b) => a - b))}
          size="sm"
        >
          {generating ? 'Gerando...' : 'Gerar XML'}
        </Button>
        <Button
          leadingIcon={<FolderOpen className="h-3.5 w-3.5" />}
          onClick={() => onOpenPath(xml?.outputPath ?? analysis.analysisPath)}
          size="sm"
          variant="quiet"
        >
          Abrir pasta
        </Button>
        {durationsChanged ? (
          <Button leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onResegment} size="sm" variant="quiet">
            Refazer clipes ({durations.minSec}–{durations.targetSec}–{durations.maxSec}s)
          </Button>
        ) : null}
      </div>

      {!hasTemplate ? <p className="border-t border-line px-3 py-2 text-xs text-status-warn">Escolha o molde no Inspetor.</p> : null}
      {xml?.status === 'done' && xml.outputPath ? (
        <p className="border-t border-line px-3 py-2 text-xs text-status-green">
          XML salvo: <span className="font-mono">{getFileName(xml.outputPath)}</span>. No Premiere: Arquivo › Importar.
        </p>
      ) : null}
      {xml?.status === 'error' ? <p className="border-t border-line px-3 py-2 text-xs text-status-red">{xml.error}</p> : null}
    </div>
  )
}
