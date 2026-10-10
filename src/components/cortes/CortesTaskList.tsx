import { CortesTaskItem } from '@/components/cortes/CortesTaskItem'
import { summarizeQueue } from '@/lib/utils'
import type { CortesDurations, CortesTask } from '@/types/cortes'

interface CortesTaskListProps {
  tasks: CortesTask[]
  templatePath: string
  durations: CortesDurations
  onCancel: (taskId: string) => void
  onRetry: (task: CortesTask) => void
  onResegment: (task: CortesTask) => void
  onGenerateXml: (task: CortesTask, clips: number[]) => void
  onOpenPath: (path: string) => void
}

export function CortesTaskList({ tasks, ...itemProps }: CortesTaskListProps) {
  return (
    <section aria-label="Fila de cortes" className="overflow-hidden rounded-[10px] border border-line bg-panel">
      <header className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-2.5">
        <h2 className="text-[13px] font-semibold text-text-primary">Fila</h2>
        <span className="text-xs text-text-muted">{summarizeQueue(tasks)}</span>
      </header>

      {tasks.length === 0 ? (
        <p className="px-4 py-10 text-center text-sm text-text-muted">
          Nenhum react analisado ainda. Solte o bruto acima e clique em Analisar.
        </p>
      ) : (
        <ul className="divide-y divide-line">
          {tasks.map((task) => (
            <CortesTaskItem key={task.id} task={task} {...itemProps} />
          ))}
        </ul>
      )}
    </section>
  )
}
