import { FolderOpen, Upload } from 'lucide-react'
import { useState } from 'react'

import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

interface DropZoneProps {
  onPickFiles: () => Promise<{ ok: boolean; message: string | null }>
  onDropPaths: (paths: string[]) => Promise<{ ok: boolean; message: string | null }>
}

type DragFile = File & { path?: string }

export function DropZone({ onPickFiles, onDropPaths }: DropZoneProps) {
  // Controla o destaque visual da area de drop e mensagens de erro locais.
  const [isOver, setIsOver] = useState(false)
  const [dropError, setDropError] = useState<string | null>(null)

  // Resolve os caminhos reais dos arquivos arrastados antes de mandar para a fila.
  async function handleDrop(files: FileList | null) {
    setIsOver(false)
    if (!files) {
      return
    }

    const paths = Array.from(files)
      .map((file) => window.clipforge?.dialog?.getPathForFile(file) || (file as DragFile).path)
      .filter((path): path is string => Boolean(path))

    if (paths.length > 0) {
      const result = await onDropPaths(paths)
      setDropError(result.message)
    } else if (files.length > 0) {
      setDropError('Não deu pra ler o caminho do arquivo arrastado. Use "Escolher arquivos".')
    }
  }

  return (
    <div className="space-y-2">
      <div
        className={cn(
          'flex items-center gap-4 rounded-[10px] border border-dashed px-5 py-4 transition-colors duration-150',
          isOver ? 'border-accent bg-accent-soft' : 'border-line-strong bg-panel',
        )}
        onDragEnter={(event) => {
          event.preventDefault()
          setIsOver(true)
        }}
        onDragLeave={(event) => {
          // So apaga o destaque quando o cursor sai da area, nao ao passar por um filho.
          if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
            setIsOver(false)
          }
        }}
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault()
          void handleDrop(event.dataTransfer.files)
        }}
      >
        <Upload className={cn('h-5 w-5 shrink-0', isOver ? 'text-accent' : 'text-text-muted')} />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium text-text-primary">{isOver ? 'Pode soltar' : 'Solte vídeos ou áudios aqui'}</p>
          <p className="text-xs text-text-muted">mp4, mov, mkv, mp3, wav, m4a. Entram na fila e rodam um por vez.</p>
        </div>
        <Button
          leadingIcon={<FolderOpen className="h-4 w-4" />}
          onClick={() => {
            setDropError(null)
            void onPickFiles().then((result) => setDropError(result.message))
          }}
          size="sm"
        >
          Escolher arquivos
        </Button>
      </div>

      {dropError ? <p className="text-sm text-status-warn">{dropError}</p> : null}
    </div>
  )
}
