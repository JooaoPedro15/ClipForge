import { FolderSearch, Flame, LoaderCircle, RotateCcw, Square, ThumbsDown, ThumbsUp, TriangleAlert } from 'lucide-react'

import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { formatDuration, formatTaskStatus, formatTimestamp } from '@/lib/utils'
import type { ClipFeedbackLabel, ClipSplitterClip, ClipSplitterTask } from '@/types/clipSplitter'

interface TaskItemProps {
  task: ClipSplitterTask
  onCancel: (taskId: string) => void
  onOpenOutput: (outputDir: string | null) => void
  onRetry: (sourcePath: string) => void
  onSaveFeedback: (taskId: string, clip: ClipSplitterClip, label: ClipFeedbackLabel | null) => void | Promise<unknown>
}

// Mapeia o status da tarefa para a cor do badge principal.
function resolveTone(status: ClipSplitterTask['status']) {
  switch (status) {
    case 'completed':
      return 'green'
    case 'processing':
    case 'preparing':
      return 'yellow'
    case 'queued':
      return 'blue'
    case 'error':
    case 'cancelled':
      return 'red'
    default:
      return 'neutral'
  }
}

// Mantem consistente a cor usada para o feedback salvo em cada clipe.
function resolveFeedbackTone(label: ClipFeedbackLabel | null | undefined) {
  switch (label) {
    case 'viral':
      return 'green'
    case 'good':
      return 'blue'
    case 'weak':
      return 'red'
    default:
      return 'neutral'
  }
}

// Traduz o feedback salvo para um rotulo amigavel na interface.
function formatFeedbackLabel(label: ClipFeedbackLabel | null | undefined) {
  switch (label) {
    case 'viral':
      return 'Viral'
    case 'good':
      return 'Bom'
    case 'weak':
      return 'Fraco'
    default:
      return 'Sem feedback'
  }
}

export function ClipSplitterTaskItem({ task, onCancel, onOpenOutput, onRetry, onSaveFeedback }: TaskItemProps) {
  // Estados ativos sao os que ainda permitem cancelamento e mostram progresso.
  const isActive = task.status === 'queued' || task.status === 'preparing' || task.status === 'processing'

  return (
    <Card className="space-y-5">
      {/* Cabecalho do job com status, modo de corte e indicacao de IA/fallback. */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="text-lg font-medium text-text-primary">{task.sourceName}</h4>
            <Badge tone={resolveTone(task.status)}>{formatTaskStatus(task.status)}</Badge>
            <Badge>{task.mode === 'silence' ? 'Pre-edicao' : 'Fixo'}</Badge>
          </div>
          <p className="font-mono text-xs text-text-muted">{task.sourcePath}</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {isActive ? (
            <Button leadingIcon={<Square className="h-3.5 w-3.5" />} onClick={() => onCancel(task.id)} variant="danger">
              Cancelar
            </Button>
          ) : null}
          {task.outputDir ? (
            <Button
              leadingIcon={<FolderSearch className="h-4 w-4" />}
              onClick={() => onOpenOutput(task.outputDir)}
              variant="ghost"
            >
              Abrir pasta
            </Button>
          ) : null}
          {(task.status === 'error' || task.status === 'cancelled') && (
            <Button leadingIcon={<RotateCcw className="h-4 w-4" />} onClick={() => onRetry(task.sourcePath)} variant="ghost">
              Tentar de novo
            </Button>
          )}
        </div>
      </div>

      {/* Mensagem atual do runner e barra de progresso da exportacao. */}
      <div className="space-y-3">
        <div className="flex items-center justify-between text-sm">
          <p className="text-text-secondary">{task.message}</p>
          <span className="font-mono text-xs text-text-muted">
            {task.progress !== null ? `${task.progress}%` : task.queuePosition ? `Fila ${task.queuePosition}` : '--'}
          </span>
        </div>

        <div className="h-2 overflow-hidden rounded-full bg-white/6">
          <div
            className="h-full rounded-full bg-gradient-to-r from-white via-white/80 to-white/50 transition-[width] duration-300"
            style={{ width: `${task.progress ?? (task.status === 'queued' ? 8 : 16)}%` }}
          />
        </div>
      </div>

      {/* Resumo tecnico do job: volume de clips, duracoes e pasta final. */}
      <div className="grid gap-3 text-sm text-text-secondary sm:grid-cols-2 xl:grid-cols-4">
        <div className="rounded-2xl border border-white/8 bg-black/12 px-4 py-3">
          <p className="text-xs uppercase tracking-[0.2em] text-text-muted">Saidas</p>
          <p className="mt-1 font-medium text-text-primary">
            {task.totalClips ? `${task.clipsCreated}/${task.totalClips}` : task.clipsCreated || '--'}
          </p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-black/12 px-4 py-3">
          <p className="text-xs uppercase tracking-[0.2em] text-text-muted">Fonte</p>
          <p className="mt-1 font-medium text-text-primary">{formatDuration(task.sourceDurationSec)}</p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-black/12 px-4 py-3">
          <p className="text-xs uppercase tracking-[0.2em] text-text-muted">Job</p>
          <p className="mt-1 font-medium text-text-primary">{formatDuration(task.durationSec)}</p>
        </div>
        <div className="rounded-2xl border border-white/8 bg-black/12 px-4 py-3">
          <p className="text-xs uppercase tracking-[0.2em] text-text-muted">Saida</p>
          <p className="mt-1 truncate font-medium text-text-primary">{task.outputDir ?? '--'}</p>
        </div>
      </div>

      {/* Rodape com horarios, erros e contexto de fallback/local. */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-text-muted">
        <span>Inicio: {formatTimestamp(task.startedAt)}</span>
        {task.completedAt ? <span>Fim: {formatTimestamp(task.completedAt)}</span> : null}
        {task.error ? (
          <span className="inline-flex items-center gap-1 text-status-red">
            <TriangleAlert className="h-3.5 w-3.5" />
            {task.error}
          </span>
        ) : null}
        {task.debugPath ? <span>Debug: {task.debugPath}</span> : null}
        {isActive ? (
          <span className="inline-flex items-center gap-1 text-status-yellow">
            <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
            Exportando em tempo real
          </span>
        ) : null}
      </div>

      {task.status === 'completed' && task.clips.length > 0 ? (
        // Painel que transforma cada clipe exportado em dado de treino/manual feedback.
        <div className="space-y-3 rounded-2xl border border-white/8 bg-black/12 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-text-secondary">Arquivo de pré-edição</p>
              <p className="mt-1 text-sm text-text-secondary">
                Video unico em ordem original, pronto para revisao manual.
              </p>
            </div>
            <Badge tone="blue">Pre-edicao</Badge>
          </div>

          <div className="space-y-3">
            {/* Cada card permite revisar rapidamente o motivo do corte e dar feedback. */}
            {task.clips.map((clip) => (
              <div key={clip.clipId} className="rounded-2xl border border-white/8 bg-black/16 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="space-y-2">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="text-sm font-medium text-text-primary">
                        Video limpo {String(clip.index).padStart(2, '0')} • {formatDuration(clip.durationSec)}
                      </p>
                      <Badge tone={resolveFeedbackTone(clip.feedbackLabel)}>{formatFeedbackLabel(clip.feedbackLabel)}</Badge>
                    </div>
                    <p className="text-sm text-text-secondary">{clip.reason}</p>
                    <p className="max-w-3xl text-xs leading-6 text-text-muted">{clip.transcriptSnippet}</p>
                  </div>

                  <Button
                    leadingIcon={<FolderSearch className="h-4 w-4" />}
                    onClick={() => onOpenOutput(clip.filePath)}
                    variant="ghost"
                  >
                    Revelar arquivo
                  </Button>
                </div>

              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  )
}
