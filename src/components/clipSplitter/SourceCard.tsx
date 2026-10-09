import { Film, FolderOpen, Scissors, Upload } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { cn, getFileName } from '@/lib/utils'

interface SourceCardProps {
  sourcePath: string | null
  outputDir: string | null
  message: string | null
  onPickSource: () => void
  onDropSource: (path: string) => void
  onPickOutputDir: () => void
  onResetOutputDir: () => void
  onStart: () => void
}

type DragFile = File & { path?: string }

// Pasta padrao do Python: irma do video, com o nome dele + _preedit.
function defaultOutputName(sourcePath: string): string {
  return `${getFileName(sourcePath).replace(/\.[^.]+$/, '')}_preedit`
}

// Entrada do Pre-Editor: o video bruto, onde salvar e o botao que comeca.
export function SourceCard({ sourcePath, outputDir, message, onPickSource, onDropSource, onPickOutputDir, onResetOutputDir, onStart }: SourceCardProps) {
  const [isOver, setIsOver] = useState(false)
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
            {sourcePath ? getFileName(sourcePath) : isOver ? 'Pode soltar' : 'Solte o vídeo bruto aqui'}
          </p>
          <p className="truncate text-xs text-text-muted">{folder ?? 'Live, gameplay longo, gravação inteira. Um arquivo por vez.'}</p>
        </div>
        <Button leadingIcon={<FolderOpen className="h-4 w-4" />} onClick={onPickSource} size="sm" variant={sourcePath ? 'quiet' : 'primary'}>
          {sourcePath ? 'Trocar' : 'Escolher vídeo'}
        </Button>
      </div>

      {sourcePath ? (
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line px-5 py-3">
          <div className="min-w-0 flex-1 text-xs">
            <span className="text-text-muted">Salvar em </span>
            <span className="font-mono text-text-secondary" title={outputDir ?? undefined}>
              {outputDir ? getFileName(outputDir) : defaultOutputName(sourcePath)}
            </span>
            {outputDir ? null : <span className="text-text-muted"> ao lado do vídeo</span>}
            <span className="ml-2 inline-flex gap-1 align-middle">
              <button className="app-no-drag text-text-muted underline-offset-2 hover:text-text-primary hover:underline" onClick={onPickOutputDir} type="button">
                mudar
              </button>
              {outputDir ? (
                <button className="app-no-drag text-text-muted underline-offset-2 hover:text-text-primary hover:underline" onClick={onResetOutputDir} type="button">
                  usar padrão
                </button>
              ) : null}
            </span>
          </div>
          <Button leadingIcon={<Scissors className="h-4 w-4" />} onClick={onStart}>
            Gerar pré-edição
          </Button>
        </div>
      ) : null}

      {message ? <p className="border-t border-line px-5 py-2.5 text-sm text-status-warn">{message}</p> : null}
    </div>
  )
}
