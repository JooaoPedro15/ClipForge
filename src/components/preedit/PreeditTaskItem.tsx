import { FileCode2, FolderOpen, RotateCcw, Square, TriangleAlert } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { TaskStatusIcon, ThinProgress } from '@/components/ui/TaskStatusIcon'
import { editSummary, teachSummary } from '@/lib/preeditSummary'
import { formatDuration, getFileName } from '@/lib/utils'
import type { PreeditTask } from '@/types/preedit'

interface PreeditTaskItemProps {
  task: PreeditTask
  onCancel: (taskId: string) => void
  onRetry: (task: PreeditTask) => void
  onOpenPath: (path: string) => void
}

function isActive(task: PreeditTask): boolean {
  return task.status === 'queued' || task.status === 'preparing' || task.status === 'processing'
}

// Linha de status: o que esta rodando agora ou o resumo do que saiu.
function describe(task: PreeditTask): string {
  switch (task.status) {
    case 'queued':
      return 'Esperando a GPU liberar.'
    case 'completed':
      return task.kind === 'edit' ? editSummary(task.result ?? {}) : teachSummary(task.result ?? {})
    case 'cancelled':
      return 'Cancelado.'
    case 'error':
      return task.kind === 'edit' ? 'A pré-edição parou com erro.' : 'O ensino parou com erro.'
    default:
      return task.message
  }
}

function rightMeta(task: PreeditTask): string {
  if (task.status === 'processing' || task.status === 'preparing') {
    return task.progress !== null ? `${task.progress}%` : ''
  }
  if (task.status === 'queued') {
    return task.queuePosition ? `${task.queuePosition}º na fila` : ''
  }
  if (task.status === 'completed' && task.startedAt && task.completedAt) {
    return formatDuration((task.completedAt - task.startedAt) / 1000)
  }
  return ''
}

export function PreeditTaskItem({ task, onCancel, onRetry, onOpenPath }: PreeditTaskItemProps) {
  const active = isActive(task)
  const running = task.status === 'preparing' || task.status === 'processing'
  const xmlPath = task.status === 'completed' && typeof task.result?.xmlPath === 'string' ? task.result.xmlPath : null

  return (
    <li className="flex gap-3 px-4 py-3.5">
      <div className="pt-0.5">
        <TaskStatusIcon progress={task.progress} status={task.status} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-3">
          <p className="truncate text-sm font-medium text-text-primary">{task.title}</p>
          <span className="ml-auto shrink-0 font-mono text-xs text-text-muted tabular-nums">{rightMeta(task)}</span>
        </div>
        <p className="mt-0.5 text-xs text-text-secondary">{describe(task)}</p>
        {running ? (
          <div className="mt-2">
            <ThinProgress value={task.progress} />
          </div>
        ) : null}

        {task.warnings.length > 0 ? (
          <ul className="mt-2 space-y-1 rounded-md border border-status-warn/30 bg-status-warn/10 px-2.5 py-2">
            {task.warnings.map((warning) => (
              <li className="flex items-start gap-1.5 text-xs text-status-warn" key={warning}>
                <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
                {warning}
              </li>
            ))}
          </ul>
        ) : null}

        {task.error && task.status === 'error' ? (
          <p className="mt-1.5 flex items-start gap-1.5 text-xs text-status-red">
            <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
            {task.error}
          </p>
        ) : null}

        {xmlPath ? (
          <div className="mt-2 flex items-center gap-2 rounded-md border border-line bg-raised px-2.5 py-1.5">
            <FileCode2 className="h-3.5 w-3.5 shrink-0 text-text-muted" />
            <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-primary" title={xmlPath}>
              {getFileName(xmlPath)}
            </span>
            <Button leadingIcon={<FolderOpen className="h-3.5 w-3.5" />} onClick={() => onOpenPath(xmlPath)} size="sm" variant="quiet">
              Abrir pasta
            </Button>
          </div>
        ) : null}

        {active || task.status === 'error' || task.status === 'cancelled' ? (
          // -ml compensa o padding dos botoes discretos pro icone alinhar com o texto acima.
          <div className="mt-2 -ml-2.5 flex flex-wrap gap-1">
            {active ? (
              <Button leadingIcon={<Square className="h-3 w-3" />} onClick={() => onCancel(task.id)} size="sm" variant="quiet">
                Cancelar
              </Button>
            ) : (
              <Button leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => onRetry(task)} size="sm" variant="quiet">
                Tentar de novo
              </Button>
            )}
          </div>
        ) : null}
      </div>
    </li>
  )
}
