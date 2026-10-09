import { PAUSE_LABELS, simulatePreEdit, type PreviewBlock } from '@/lib/pausePreview'
import { cn } from '@/lib/utils'
import type { ClipSplitterPreEditMode } from '@/types/clipSplitter'

interface PauseDiagramProps {
  mode: ClipSplitterPreEditMode
  // Modo "fixed" exporta o bruto inteiro: as duas trilhas ficam iguais.
  compress: boolean
}

const seconds = (value: number) => `${value.toFixed(1).replace('.', ',')}s`

function Track({ label, blocks, totalSec, scaleSec, pick }: {
  label: string
  blocks: PreviewBlock[]
  totalSec: number
  scaleSec: number
  pick: (block: PreviewBlock) => number
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="w-12 shrink-0 text-[11px] text-text-muted">{label}</span>
      {/* A largura da trilha e proporcional a duracao total: a de baixo encolhe de verdade. */}
      <div className="min-w-0 flex-1">
        <div
          className="flex h-7 items-stretch gap-px transition-[width] duration-500 ease-out"
          style={{ width: `${(totalSec / scaleSec) * 100}%` }}
        >
          {blocks.map((block, index) => {
            const value = pick(block)
            const isSpeech = block.kind === 'speech'
            return (
              <span
                className={cn(
                  'relative min-w-0 rounded-[3px] transition-[flex-grow] duration-500 ease-out',
                  isSpeech ? 'bg-text-secondary/75' : 'border-y border-dashed border-white/35',
                )}
                key={index}
                style={{ flexGrow: value, flexBasis: 0 }}
                title={block.kind === 'speech' ? `Fala: ${seconds(block.beforeSec)}` : `${PAUSE_LABELS[block.kind]}: ${seconds(block.beforeSec)} → ${seconds(value)}`}
              />
            )
          })}
        </div>
      </div>
      <span className="w-10 shrink-0 text-right font-mono text-[11px] text-text-secondary tabular-nums">{seconds(totalSec)}</span>
    </div>
  )
}

// Timeline de exemplo: o mesmo trecho antes e depois, com as regras reais de cada pausa.
export function PauseDiagram({ mode, compress }: PauseDiagramProps) {
  const result = simulatePreEdit(mode)
  const afterSec = compress ? result.afterSec : result.beforeSec
  const saved = Math.round((1 - afterSec / result.beforeSec) * 100)

  return (
    <figure aria-label="Exemplo de pré-edição de um trecho de gameplay" className="overflow-hidden rounded-lg border border-line bg-monitor">
      <div className="space-y-2.5 px-3 pt-4 pb-3">
        <Track blocks={result.blocks} label="Bruto" pick={(block) => block.beforeSec} scaleSec={result.beforeSec} totalSec={result.beforeSec} />
        <Track
          blocks={result.blocks}
          label="Depois"
          pick={(block) => (compress ? block.afterSec : block.beforeSec)}
          scaleSec={result.beforeSec}
          totalSec={afterSec}
        />
      </div>
      <figcaption className="flex items-center justify-between gap-3 border-t border-line bg-panel px-3 py-2 text-xs">
        <span className="flex items-center gap-3 text-text-muted">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-3 rounded-[2px] bg-text-secondary/75" />
            fala
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2 w-3 border-y border-dashed border-white/40" />
            pausa
          </span>
        </span>
        <span className="whitespace-nowrap text-text-secondary">{compress ? `${saved}% mais curto` : 'Sem cortes'}</span>
      </figcaption>
    </figure>
  )
}
