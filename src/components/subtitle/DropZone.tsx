import { FolderOpen } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { Button } from '@/components/ui/Button'
import { cn } from '@/lib/utils'

type ActionResult = { ok: boolean; message: string | null }

interface DropZoneProps {
  title: string
  hint: string
  icon: ReactNode
  buttonLabel: string
  onPickFiles: () => Promise<ActionResult>
  onDropPaths: (paths: string[]) => Promise<ActionResult>
}

type DragFile = File & { path?: string }

// Uma entrada da fila: cada uma tem a sua intencao (legendar ou versao em chines),
// entao o que acontece com o arquivo depende de onde ele foi solto, nao de uma opcao escondida.
export function DropZone({ title, hint, icon, buttonLabel, onPickFiles, onDropPaths }: DropZoneProps) {
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
      setDropError(`Não deu pra ler o caminho do arquivo arrastado. Use "${buttonLabel}".`)
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        className={cn(
          'flex flex-1 flex-col gap-3 rounded-[10px] border border-dashed p-4 transition-colors duration-150',
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
        <div className="flex items-start gap-3">
          <span className={cn('mt-0.5 shrink-0', isOver ? 'text-accent' : 'text-text-muted')}>{icon}</span>
          <div className="min-w-0">
            <p className="text-sm font-medium text-text-primary">{isOver ? 'Pode soltar' : title}</p>
            <p className="mt-0.5 text-xs leading-snug text-text-muted">{hint}</p>
          </div>
        </div>
        <Button
          className="mt-auto self-start"
          leadingIcon={<FolderOpen className="h-4 w-4" />}
          onClick={() => {
            setDropError(null)
            void onPickFiles().then((result) => setDropError(result.message))
          }}
          size="sm"
          variant="ghost"
        >
          {buttonLabel}
        </Button>
      </div>

      {dropError ? <p className="text-sm text-status-warn">{dropError}</p> : null}
    </div>
  )
}
