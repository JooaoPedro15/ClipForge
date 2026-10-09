import { ClipSplitterTaskItem } from '@/components/clipSplitter/TaskItem'
import { summarizeQueue } from '@/lib/utils'
import type { ClipSplitterTask } from '@/types/clipSplitter'

interface TaskListProps {
  tasks: ClipSplitterTask[]
  onCancel: (taskId: string) => void
  onOpenOutput: (outputDir: string | null) => void
  onRetry: (sourcePath: string) => void
}

export function ClipSplitterTaskList({ tasks, onCancel, onOpenOutput, onRetry }: TaskListProps) {
  return (
    <section aria-label="Fila de pré-edição" className="overflow-hidden rounded-[10px] border border-line bg-panel">
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-text-primary">Fila</h2>
        <span className="text-xs text-text-muted">{summarizeQueue(tasks)}</span>
      </header>

      {tasks.length === 0 ? (
        // Placeholder inicial mostrado antes de qualquer exportacao.
        <p className="px-4 py-10 text-center text-sm text-text-muted">
          Nenhuma pré-edição ainda. Escolha o vídeo bruto acima e clique em Gerar pré-edição.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {tasks.map((task) => (
            <ClipSplitterTaskItem key={task.id} onCancel={onCancel} onOpenOutput={onOpenOutput} onRetry={onRetry} task={task} />
          ))}
        </ul>
      )}
    </section>
  )
}
