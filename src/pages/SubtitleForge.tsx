import { Languages, Upload } from 'lucide-react'

import { Workspace } from '@/components/layout/Workspace'
import { DropZone } from '@/components/subtitle/DropZone'
import { SubtitleInspector } from '@/components/subtitle/SubtitleInspector'
import { TaskList } from '@/components/subtitle/TaskList'
import type { QueueRequest } from '@/hooks/useSubtitleForge'
import { useAppStore } from '@/store/appStore'
import type { HardsubMode } from '@/types/subtitle'

interface SubtitleForgePageProps {
  title: string
  description: string
  onPickFiles: (request?: QueueRequest) => Promise<{ ok: boolean; message: string | null }>
  onDropPaths: (paths: string[], request?: QueueRequest) => Promise<{ ok: boolean; message: string | null }>
  onCancelTask: (taskId: string) => void
  onOpenOutput: (outputPath: string | null) => void
  onRetryTask: (filePath: string, autoBurn: HardsubMode | null) => void
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
      {/* Duas entradas, uma por intencao: o lugar onde o arquivo e solto decide o que sai.
          Lado a lado quando cabe (container query), uma embaixo da outra na janela estreita. */}
      <div className="@container">
        <div className="grid gap-3 @lg:grid-cols-2">
          <DropZone
            buttonLabel="Escolher arquivos"
            hint="Solte o bruto ou o áudio. Sai o .srt pra editar no Premiere."
            icon={<Upload className="h-5 w-5" />}
            onDropPaths={(paths) => onDropPaths(paths)}
            onPickFiles={() => onPickFiles()}
            title="Legendar"
          />
          <DropZone
            buttonLabel="Escolher vídeo pronto"
            hint="Solte o vídeo final. Ele transcreve, traduz e queima sozinho: sai o .hardsub.zh.mp4 ao lado."
            icon={<Languages className="h-5 w-5" />}
            onDropPaths={(paths) => onDropPaths(paths, { autoBurn: 'zh' })}
            onPickFiles={() => onPickFiles({ autoBurn: 'zh' })}
            title="Versão em chinês"
          />
        </div>
      </div>
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
