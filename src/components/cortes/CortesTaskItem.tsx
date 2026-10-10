import { RotateCcw, Square, TriangleAlert } from 'lucide-react'

import { CortesClipList } from '@/components/cortes/CortesClipList'
import { Button } from '@/components/ui/Button'
import { TaskStatusIcon, ThinProgress } from '@/components/ui/TaskStatusIcon'
import { cortesStep, formatClock } from '@/lib/cortesClips'
import { formatDuration } from '@/lib/utils'
import { isCortesActive } from '@/store/cortesTasks'
import type { CortesDurations, CortesTask } from '@/types/cortes'

interface CortesTaskItemProps {
  task: CortesTask
  templatePath: string
  durations: CortesDurations
  onCancel: (taskId: string) => void
  onRetry: (task: CortesTask) => void
  onResegment: (task: CortesTask) => void
  onGenerateXml: (task: CortesTask, clips: number[]) => void
  onOpenPath: (path: string) => void
}

// Linha de status: o que esta rodando agora ou o que a analise achou.
function describe(task: CortesTask): string {
  switch (task.status) {
    case 'queued':
      return task.kind === 'resegment' ? 'Esperando a GPU pra refazer os clipes.' : 'Esperando a GPU liberar.'
    case 'completed': {
      const analysis = task.analysis
      if (!analysis) {
        return 'Pronto.'
      }
      const count = analysis.clips.length
      const loaded = task.stage === 'loaded' ? ' Análise anterior, sem reprocessar.' : ''
      return `${count} ${count === 1 ? 'clipe' : 'clipes'} entre ${formatClock(analysis.start)} e ${formatClock(analysis.end)}.${loaded}`
    }
    case 'cancelled':
      return 'Cancelado.'
    case 'error':
      return task.kind === 'resegment' ? 'Refazer os clipes parou com erro.' : 'A análise parou com erro.'
    default:
      return task.message
  }
}

function rightMeta(task: CortesTask): string {
  if (task.status === 'processing' || task.status === 'preparing') {
    return task.progress !== null ? `${task.progress}%` : ''
  }
  if (task.status === 'queued') {
    return task.queuePosition ? `${task.queuePosition}º na fila` : ''
  }
  return task.status === 'completed' && task.durationSec !== null ? formatDuration(task.durationSec) : ''
}

export function CortesTaskItem({ task, templatePath, durations, onCancel, onRetry, onResegment, onGenerateXml, onOpenPath }: CortesTaskItemProps) {
  const isActive = isCortesActive(task.status)
  const isRunning = task.status === 'preparing' || task.status === 'processing'
  const step = isRunning ? cortesStep(task.stage) : null
  const analysis = task.status === 'completed' ? task.analysis : null

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
          {step ? (
            <span className="shrink-0 rounded bg-raised px-1.5 py-px text-[11px] font-medium text-text-secondary">
              Etapa {step.index}/4 · {step.label}
            </span>
          ) : null}
          <span className="ml-auto shrink-0 font-mono text-xs text-text-muted tabular-nums">{rightMeta(task)}</span>
        </div>
        <p className="mt-0.5 text-xs text-text-secondary">{describe(task)}</p>
        {isRunning ? (
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

        {analysis ? (
          <CortesClipList
            analysis={analysis}
            durations={durations}
            // Lista nova (refazer clipes) recomeca a selecao.
            key={`${analysis.analysisPath}:${task.completedAt ?? 'carregada'}`}
            onGenerateXml={(clips) => onGenerateXml(task, clips)}
            onOpenPath={onOpenPath}
            onResegment={() => onResegment(task)}
            templatePath={templatePath}
            xml={task.xml}
          />
        ) : null}

        {isActive || task.status === 'error' || task.status === 'cancelled' ? (
          // -ml compensa o padding dos botoes discretos pro icone alinhar com o texto acima.
          <div className="mt-2 -ml-2.5 flex flex-wrap gap-1">
            {isActive ? (
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
