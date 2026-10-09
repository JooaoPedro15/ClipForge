import { TaskItem } from '@/components/subtitle/TaskItem'
import type { HardsubMode, SubtitleTask } from '@/types/subtitle'

interface TaskListProps {
  tasks: SubtitleTask[]
  onCancel: (taskId: string) => void
  onOpenOutput: (outputPath: string | null) => void
  onRetry: (filePath: string) => void
  onBurn: (taskId: string, mode: HardsubMode) => void
}

// Contagem curta por estado pro cabecalho da fila.
function summarize(tasks: SubtitleTask[]): string {
  const running = tasks.filter((task) => task.status === 'processing' || task.status === 'preparing').length
  const waiting = tasks.filter((task) => task.status === 'queued').length
  const done = tasks.filter((task) => task.status === 'completed').length
  return [
    running ? `${running} rodando` : null,
    waiting ? `${waiting} esperando` : null,
    done ? `${done} ${done === 1 ? 'pronta' : 'prontas'}` : null,
  ]
    .filter(Boolean)
    .join(', ')
}

export function TaskList({ tasks, onCancel, onOpenOutput, onRetry, onBurn }: TaskListProps) {
  return (
    <section aria-label="Fila de legendas" className="overflow-hidden rounded-[10px] border border-line bg-panel">
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-text-primary">Fila</h2>
        <span className="text-xs text-text-muted">{summarize(tasks)}</span>
      </header>

      {tasks.length === 0 ? (
        // Estado vazio exibido antes da primeira tarefa entrar na fila.
        <p className="px-4 py-10 text-center text-sm text-text-muted">
          Nada na fila ainda. Os vídeos que você soltar aparecem aqui, com o progresso de cada um.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {tasks.map((task) => (
            <TaskItem key={task.id} onBurn={onBurn} onCancel={onCancel} onOpenOutput={onOpenOutput} onRetry={onRetry} task={task} />
          ))}
        </ul>
      )}
    </section>
  )
}
