import { FileJson, FolderOpen, FolderSearch, RotateCcw, Square, TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { TaskStatusIcon, ThinProgress } from '@/components/ui/TaskStatusIcon'
import { formatDuration } from '@/lib/utils'
import type { ClipSplitterTask } from '@/types/clipSplitter'

interface TaskItemProps {
  task: ClipSplitterTask
  onCancel: (taskId: string) => void
  onOpenOutput: (outputDir: string | null) => void
  onRetry: (sourcePath: string) => void
}

// Linha de status: o que esta rodando ou quanto o bruto encolheu.
function describe(task: ClipSplitterTask): string {
  const clip = task.clips[0]
  switch (task.status) {
    case 'queued':
      return 'Esperando a GPU liberar.'
    case 'completed':
      if (clip && task.sourceDurationSec) {
        const saved = Math.round((1 - clip.durationSec / task.sourceDurationSec) * 100)
        return `${formatDuration(task.sourceDurationSec)} de bruto viraram ${formatDuration(clip.durationSec)} (${saved}% mais curto).`
      }
      return 'Pré-edição pronta.'
    case 'cancelled':
      return 'Cancelada.'
    case 'error':
      return 'A pré-edição parou com erro.'
    default:
      return task.message
  }
}

function rightMeta(task: ClipSplitterTask): string {
  if (task.status === 'processing' || task.status === 'preparing') {
    return task.progress !== null ? `${task.progress}%` : ''
  }
  if (task.status === 'queued') {
    return task.queuePosition ? `${task.queuePosition}º na fila` : ''
  }
  return task.status === 'completed' ? formatDuration(task.durationSec) : ''
}

export function ClipSplitterTaskItem({ task, onCancel, onOpenOutput, onRetry }: TaskItemProps) {
  // Estados ativos sao os que ainda permitem cancelamento e mostram progresso.
  const isActive = task.status === 'queued' || task.status === 'preparing' || task.status === 'processing'
  const isRunning = task.status === 'preparing' || task.status === 'processing'
  const clip = task.status === 'completed' ? task.clips[0] : undefined

  return (
    <li className="flex gap-3 px-4 py-3.5">
      <div className="pt-0.5">
        <TaskStatusIcon progress={task.progress} status={task.status} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-3">
          <p className="truncate text-sm font-medium text-text-primary" title={task.sourcePath}>
            {task.sourceName}
          </p>
          {task.mode === 'fixed' ? <span className="shrink-0 text-xs text-text-muted">sem cortes</span> : null}
          <span className="ml-auto shrink-0 font-mono text-xs text-text-muted tabular-nums">{rightMeta(task)}</span>
        </div>
        <p className="mt-0.5 text-xs text-text-secondary">{describe(task)}</p>
        {isRunning ? (
          <div className="mt-2">
            <ThinProgress value={task.progress} />
          </div>
        ) : null}

        {task.error ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-xs text-status-red">
            <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
            {task.error}
          </p>
        ) : null}

        {/* -ml compensa o padding dos botoes discretos pro icone alinhar com o texto acima. */}
        <div className="mt-2 -ml-2.5 flex flex-wrap gap-1">
          {isActive ? (
            <Button leadingIcon={<Square className="h-3 w-3" />} onClick={() => onCancel(task.id)} size="sm" variant="quiet">
              Cancelar
            </Button>
          ) : null}
          {clip ? (
            <Button leadingIcon={<FolderSearch className="h-3.5 w-3.5" />} onClick={() => onOpenOutput(clip.filePath)} size="sm" variant="quiet">
              Mostrar vídeo
            </Button>
          ) : null}
          {task.outputDir && !isActive ? (
            <Button leadingIcon={<FolderOpen className="h-3.5 w-3.5" />} onClick={() => onOpenOutput(task.outputDir)} size="sm" variant="quiet">
              Mostrar pasta
            </Button>
          ) : null}
          {task.debugPath ? (
            <Button leadingIcon={<FileJson className="h-3.5 w-3.5" />} onClick={() => onOpenOutput(task.debugPath)} size="sm" variant="quiet">
              Mostrar JSON de debug
            </Button>
          ) : null}
          {task.status === 'error' || task.status === 'cancelled' ? (
            <Button leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => onRetry(task.sourcePath)} size="sm" variant="quiet">
              Tentar de novo
            </Button>
          ) : null}
        </div>
      </div>
    </li>
  )
}
