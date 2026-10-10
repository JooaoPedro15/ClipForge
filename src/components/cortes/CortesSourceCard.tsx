import { Clapperboard, Film, FolderOpen, Upload } from 'lucide-react'
import { useId, useState } from 'react'

import { Button } from '@/components/ui/Button'
import type { CortesRange } from '@/hooks/useCortes'
import { cn, getFileName } from '@/lib/utils'

interface CortesSourceCardProps {
  sourcePath: string | null
  range: CortesRange
  message: string | null
  onRangeChange: (range: CortesRange) => void
  onPickSource: () => void
  onDropSource: (path: string) => void
  onAnalyze: () => void
}

type DragFile = File & { path?: string }

const rangeInputClass =
  'app-no-drag h-8 w-24 rounded-md border border-line bg-raised px-2.5 font-mono text-[13px] text-text-primary tabular-nums outline-none transition-colors placeholder:text-text-muted hover:border-line-strong focus:border-text-muted'

// Entrada dos Cortes: o bruto do react, o trecho opcional e o botao que comeca a analise.
export function CortesSourceCard({ sourcePath, range, message, onRangeChange, onPickSource, onDropSource, onAnalyze }: CortesSourceCardProps) {
  const [isOver, setIsOver] = useState(false)
  const startId = useId()
  const endId = useId()
  const folder = sourcePath ? sourcePath.slice(0, sourcePath.length - getFileName(sourcePath).length) : null

  return (
    <div
      className={cn(
        'rounded-[10px] border transition-colors duration-150',
        isOver ? 'border-dashed border-accent bg-accent-soft' : sourcePath ? 'border-line bg-panel' : 'border-dashed border-line-strong bg-panel',
      )}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setIsOver(false)
        }
      }}
      onDragOver={(event) => {
        event.preventDefault()
        setIsOver(true)
      }}
      onDrop={(event) => {
        event.preventDefault()
        setIsOver(false)
        const file = event.dataTransfer.files[0]
        const path = file ? window.clipforge?.dialog?.getPathForFile(file) || (file as DragFile).path : null
        if (path) {
          onDropSource(path)
        }
      }}
    >
      <div className="flex items-center gap-4 px-5 py-4">
        {sourcePath ? <Film className="h-5 w-5 shrink-0 text-text-secondary" /> : <Upload className={cn('h-5 w-5 shrink-0', isOver ? 'text-accent' : 'text-text-muted')} />}
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text-primary">
            {sourcePath ? getFileName(sourcePath) : isOver ? 'Pode soltar' : 'Solte o bruto do react aqui'}
          </p>
          <p className="truncate text-xs text-text-muted">{folder ?? 'Gravação do OBS com o filme à esquerda e a webcam à direita.'}</p>
        </div>
        <Button leadingIcon={<FolderOpen className="h-4 w-4" />} onClick={onPickSource} size="sm" variant={sourcePath ? 'quiet' : 'primary'}>
          {sourcePath ? 'Trocar' : 'Escolher bruto'}
        </Button>
      </div>

      {sourcePath ? (
        <div className="flex flex-wrap items-end gap-x-3 gap-y-2 border-t border-line px-5 py-3">
          <div className="space-y-1">
            <label className="block text-xs text-text-muted" htmlFor={startId}>
              Começar em
            </label>
            <input
              className={rangeInputClass}
              id={startId}
              onChange={(event) => onRangeChange({ ...range, start: event.target.value })}
              placeholder="0:00"
              value={range.start}
            />
          </div>
          <div className="space-y-1">
            <label className="block text-xs text-text-muted" htmlFor={endId}>
              Terminar em
            </label>
            <input
              className={rangeInputClass}
              id={endId}
              onChange={(event) => onRangeChange({ ...range, end: event.target.value })}
              placeholder="fim"
              value={range.end}
            />
          </div>
          <p className="min-w-0 flex-1 pb-1.5 text-xs text-text-muted">Opcional. Vazio = o vídeo inteiro.</p>
          <Button leadingIcon={<Clapperboard className="h-4 w-4" />} onClick={onAnalyze}>
            Analisar
          </Button>
        </div>
      ) : null}

      {message ? <p className="border-t border-line px-5 py-2.5 text-sm text-status-warn">{message}</p> : null}
    </div>
  )
}
