import { Film, FolderOpen, Plus, Upload, WandSparkles, X } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { cn, getFileName } from '@/lib/utils'

interface PreeditSourceCardProps {
  sources: string[]
  minutes: number
  message: string | null
  onPickSources: () => void
  onDropSources: (paths: string[]) => void
  onRemoveSource: (path: string) => void
  onClearSources: () => void
  onEdit: () => void
}

type DragFile = File & { path?: string }

function folderOf(path: string): string {
  return path.slice(0, path.length - getFileName(path).length)
}

// Entrada da Pre-edicao que aprende: os brutos de uma gravacao (pausou no OBS? todos), na ordem da sequencia.
export function PreeditSourceCard({ sources, minutes, message, onPickSources, onDropSources, onRemoveSource, onClearSources, onEdit }: PreeditSourceCardProps) {
  const [isOver, setIsOver] = useState(false)
  const hasSources = sources.length > 0

  return (
    <div
      className={cn(
        'rounded-[10px] border transition-colors duration-150',
        isOver ? 'border-dashed border-accent bg-accent-soft' : hasSources ? 'border-line bg-panel' : 'border-dashed border-line-strong bg-panel',
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
        const paths = [...event.dataTransfer.files]
          .map((file) => window.clipforge?.dialog?.getPathForFile(file) || (file as DragFile).path || '')
          .filter(Boolean)
        onDropSources(paths)
      }}
    >
      <div className="flex items-center gap-4 px-5 py-4">
        <Upload className={cn('h-5 w-5 shrink-0', isOver ? 'text-accent' : 'text-text-muted')} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text-primary">
            {isOver ? 'Pode soltar' : hasSources ? `${sources.length} ${sources.length === 1 ? 'bruto' : 'brutos'} da gravação` : 'Solte os brutos da gravação aqui'}
          </p>
          <p className="truncate text-xs text-text-muted">
            MKV ou MP4. Pausou no OBS? Solte todos os arquivos: viram uma sequência só, na ordem da gravação.
          </p>
        </div>
        <Button
          leadingIcon={hasSources ? <Plus className="h-4 w-4" /> : <FolderOpen className="h-4 w-4" />}
          onClick={onPickSources}
          size="sm"
          variant={hasSources ? 'quiet' : 'primary'}
        >
          {hasSources ? 'Adicionar' : 'Escolher brutos'}
        </Button>
      </div>

      {hasSources ? (
        <>
          <ol className="divide-y divide-line border-t border-line">
            {sources.map((path, index) => (
              <li className="flex items-center gap-3 px-5 py-2" key={path}>
                <span className="w-4 shrink-0 text-right font-mono text-xs text-text-muted tabular-nums">{index + 1}</span>
                <Film className="h-4 w-4 shrink-0 text-text-secondary" />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] text-text-primary">{getFileName(path)}</p>
                  <p className="truncate font-mono text-[11px] text-text-muted">{folderOf(path)}</p>
                </div>
                <button
                  aria-label={`Tirar ${getFileName(path)}`}
                  className="app-no-drag rounded p-1 text-text-muted transition-colors hover:bg-raised hover:text-text-primary"
                  onClick={() => onRemoveSource(path)}
                  type="button"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </li>
            ))}
          </ol>
          <div className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3">
            <Button onClick={onClearSources} size="sm" variant="quiet">
              Limpar
            </Button>
            <p className="min-w-0 flex-1 text-xs text-text-muted">Vídeo longo de ~{minutes} min. Duração, zoom e molde ficam no Inspetor.</p>
            <Button leadingIcon={<WandSparkles className="h-4 w-4" />} onClick={onEdit}>
              Gerar pré-edição
            </Button>
          </div>
        </>
      ) : null}

      {message ? <p className="border-t border-line px-5 py-2.5 text-sm text-status-warn">{message}</p> : null}
    </div>
  )
}
