import { Workspace } from '@/components/layout/Workspace'
import { DropZone } from '@/components/subtitle/DropZone'
import { SubtitleInspector } from '@/components/subtitle/SubtitleInspector'
import { TaskList } from '@/components/subtitle/TaskList'
import { useAppStore } from '@/store/appStore'
import type { HardsubMode } from '@/types/subtitle'

interface SubtitleForgePageProps {
  title: string
  description: string
  onPickFiles: () => Promise<{ ok: boolean; message: string | null }>
  onDropPaths: (paths: string[]) => Promise<{ ok: boolean; message: string | null }>
  onCancelTask: (taskId: string) => void
  onOpenOutput: (outputPath: string | null) => void
  onRetryTask: (filePath: string) => void
  onBurn: (taskId: string, mode: HardsubMode) => void
}

export function SubtitleForgePage({
  title,
  description,
  onPickFiles,
  onDropPaths,
  onCancelTask,
  onOpenOutput,
  onRetryTask,
  onBurn,
}: SubtitleForgePageProps) {
  // Busca as tarefas direto da store global; as configuracoes ficam no Inspetor.
  const tasks = useAppStore((state) => state.subtitleTasks)

  return (
    <Workspace description={description} inspector={<SubtitleInspector />} title={title}>
      {/* Entrada principal para drag and drop ou selecao manual de arquivos. */}
      <DropZone onDropPaths={onDropPaths} onPickFiles={onPickFiles} />
      {/* Lista detalhada das tarefas ja enviadas para o backend Python. */}
      <TaskList
        onBurn={onBurn}
        onCancel={onCancelTask}
        onOpenOutput={onOpenOutput}
        onRetry={onRetryTask}
        tasks={tasks}
      />
    </Workspace>
  )
}
