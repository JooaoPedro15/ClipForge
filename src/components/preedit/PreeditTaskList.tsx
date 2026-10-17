import { PreeditTaskItem } from '@/components/preedit/PreeditTaskItem'
import { summarizeQueue } from '@/lib/utils'
import type { PreeditTask } from '@/types/preedit'

interface PreeditTaskListProps {
  tasks: PreeditTask[]
  onCancel: (taskId: string) => void
  onRetry: (task: PreeditTask) => void
  onOpenPath: (path: string) => void
}

export function PreeditTaskList({ tasks, ...itemProps }: PreeditTaskListProps) {
  return (
    <section aria-label="Fila da pré-edição" className="overflow-hidden rounded-[10px] border border-line bg-panel">
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-text-primary">Fila</h2>
        <span className="text-xs text-text-muted">{summarizeQueue(tasks)}</span>
      </header>

      {tasks.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-text-muted">Nada ainda. Solte os brutos acima e clique em Gerar pré-edição.</p>
      ) : (
        <ul className="divide-y divide-line">
          {tasks.map((task) => (
            <PreeditTaskItem key={task.id} task={task} {...itemProps} />
          ))}
        </ul>
      )}
    </section>
  )
}
