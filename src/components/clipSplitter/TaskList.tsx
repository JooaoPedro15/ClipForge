import { Scissors } from 'lucide-react'

import { ClipSplitterTaskItem } from '@/components/clipSplitter/TaskItem'
import { Card } from '@/components/ui/Card'
import type { ClipSplitterTask } from '@/types/clipSplitter'

interface TaskListProps {
  tasks: ClipSplitterTask[]
  onCancel: (taskId: string) => void
  onOpenOutput: (outputDir: string | null) => void
  onRetry: (sourcePath: string) => void
}

export function ClipSplitterTaskList({ tasks, onCancel, onOpenOutput, onRetry }: TaskListProps) {
  // Placeholder inicial mostrado antes de qualquer exportacao.
  if (tasks.length === 0) {
    return (
      <Card className="flex min-h-[220px] items-center justify-center border-dashed bg-white/[0.03]">
        <div className="max-w-md text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-[20px] bg-white/6 text-text-secondary">
            <Scissors className="h-6 w-6" />
          </div>
          <h3 className="text-lg font-medium text-text-primary">Nenhum corte exportado ainda</h3>
          <p className="mt-2 text-sm leading-6 text-text-secondary">
            Escolha um video, ajuste a regra de split e inicie a exportacao. Os jobs aparecem aqui com progresso e
            acoes rapidas.
          </p>
        </div>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Lista de jobs com progresso e reprocessamento. */}
      {tasks.map((task) => (
        <ClipSplitterTaskItem
          key={task.id}
          onCancel={onCancel}
          onOpenOutput={onOpenOutput}
          onRetry={onRetry}
          task={task}
        />
      ))}
    </div>
  )
}
