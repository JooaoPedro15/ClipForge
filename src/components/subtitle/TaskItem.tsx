import { FolderSearch, RotateCcw, Square, TriangleAlert } from 'lucide-react'

import { BurnPanel } from '@/components/subtitle/BurnPanel'
import { Button } from '@/components/ui/Button'
import { TaskStatusIcon, ThinProgress } from '@/components/ui/TaskStatusIcon'
import { formatDuration, formatLanguage } from '@/lib/utils'
import type { HardsubMode, SubtitleTask } from '@/types/subtitle'

interface TaskItemProps {
  task: SubtitleTask
  onCancel: (taskId: string) => void
  onOpenOutput: (outputPath: string | null) => void
  onRetry: (filePath: string) => void
  onBurn: (taskId: string, mode: HardsubMode) => void
}

// Linha de status em portugues: o que a tarefa esta fazendo ou o que saiu dela.
function describe(task: SubtitleTask): string {
  switch (task.status) {
    case 'queued':
      return 'Esperando a GPU liberar.'
    case 'completed': {
      const segments = task.totalSegments ?? task.processedSegments
      const language = formatLanguage(task.detectedLanguage ?? task.language)
      return `Legenda pronta: ${segments} segmentos em ${language}, modelo ${task.model}${task.device === 'cpu' ? ' na CPU' : ''}.`
    }
    case 'cancelled':
      return 'Cancelada.'
    case 'error':
      return 'A transcrição parou com erro.'
    default:
      return task.message
  }
}

// Numero da direita: porcentagem rodando, posicao na fila ou quanto tempo levou.
function rightMeta(task: SubtitleTask): string {
  if (task.status === 'processing' || task.status === 'preparing') {
    return task.progress !== null ? `${task.progress}%` : ''
  }
  if (task.status === 'queued') {
    return task.queuePosition ? `${task.queuePosition}º na fila` : ''
  }
  return task.status === 'completed' ? formatDuration(task.durationSec) : ''
}

export function TaskItem({ task, onCancel, onOpenOutput, onRetry, onBurn }: TaskItemProps) {
  // Agrupa os estados que ainda permitem acompanhar ou cancelar o processamento.
  const isActive = task.status === 'queued' || task.status === 'preparing' || task.status === 'processing'
  const isRunning = task.status === 'preparing' || task.status === 'processing'

  return (
    <li className="flex gap-3 px-4 py-3.5">
      <div className="pt-0.5">
        <TaskStatusIcon progress={task.progress} status={task.status} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-3">
          <p className="truncate text-sm font-medium text-text-primary" title={task.filePath}>
            {task.fileName}
          </p>
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

        {/* Falha de traducao em destaque: a tarefa termina "pronta" (o .srt original saiu),
            entao um aviso discreto passava batido e o video era queimado com traducao velha. */}
        {Object.entries(task.translationErrors).map(([lang, message]) => (
          <div className="mt-2 space-y-1 rounded-md border border-status-warn/40 bg-status-warn/10 px-3 py-2 text-xs" key={lang}>
            <p className="flex items-center gap-1.5 font-medium text-status-warn">
              <TriangleAlert className="h-3.5 w-3.5" />A tradução para {formatLanguage(lang)} falhou
            </p>
            <p className="whitespace-pre-line font-mono text-text-secondary">{message}</p>
            <p className="text-text-muted">
              O .srt original saiu normal. A queima tenta traduzir de novo; se reprovar outra vez, o rascunho fica em{' '}
              <span className="font-mono">.{lang}.REJEITADO.srt</span> ao lado do vídeo.
            </p>
          </div>
        ))}

        {/* -ml compensa o padding dos botoes discretos pro icone alinhar com o texto acima. */}
        <div className="mt-2 -ml-2.5 flex flex-wrap gap-1">
          {isActive ? (
            <Button leadingIcon={<Square className="h-3 w-3" />} onClick={() => onCancel(task.id)} size="sm" variant="quiet">
              Cancelar
            </Button>
          ) : null}
          {task.outputPath && task.status === 'completed' ? (
            <Button leadingIcon={<FolderSearch className="h-3.5 w-3.5" />} onClick={() => onOpenOutput(task.outputPath)} size="sm" variant="quiet">
              Mostrar .srt
            </Button>
          ) : null}
          {Object.entries(task.translatedOutputs).map(([lang, path]) => (
            <Button key={lang} leadingIcon={<FolderSearch className="h-3.5 w-3.5" />} onClick={() => onOpenOutput(path)} size="sm" variant="quiet">
              Mostrar .{lang}.srt
            </Button>
          ))}
          {task.status === 'error' || task.status === 'cancelled' ? (
            <Button leadingIcon={<RotateCcw className="h-3.5 w-3.5" />} onClick={() => onRetry(task.filePath)} size="sm" variant="quiet">
              Tentar de novo
            </Button>
          ) : null}
        </div>

        {task.status === 'completed' ? <BurnPanel onBurn={onBurn} onOpenOutput={onOpenOutput} task={task} /> : null}
      </div>
    </li>
  )
}
