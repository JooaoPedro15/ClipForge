import { useState } from 'react'

import { PreEditInspector } from '@/components/clipSplitter/PreEditInspector'
import { SourceCard } from '@/components/clipSplitter/SourceCard'
import { ClipSplitterTaskList } from '@/components/clipSplitter/TaskList'
import { Workspace } from '@/components/layout/Workspace'
import { useAppStore } from '@/store/appStore'

type ActionResult = { ok: boolean; message: string | null }

interface ClipSplitterPageProps {
  title: string
  description: string
  /** Abre o file picker nativo para o usuário escolher a pasta de saída */
  onPickOutputDir: () => Promise<ActionResult>
  /** Abre o file picker nativo para o usuário escolher o vídeo fonte */
  onPickSourceFile: () => Promise<ActionResult>
  /** Dispara o processo de pre-edicao do bruto */
  onStartSplit: () => Promise<ActionResult>
  /** Cancela uma tarefa específica da fila, identificada pelo taskId */
  onCancelTask: (taskId: string) => void
  /** Revela o arquivo ou a pasta de saída no explorador de arquivos do SO */
  onOpenOutput: (outputDir: string | null) => void
  /** Re-executa uma tarefa que falhou, usando o mesmo sourcePath */
  onRetryTask: (sourcePath: string) => void
}

/**
 * Página do Pre-Editor: escolhe o bruto no centro, ajusta as pausas no Inspetor
 * e acompanha os jobs na fila.
 */
export function ClipSplitterPage({
  title,
  description,
  onPickOutputDir,
  onPickSourceFile,
  onStartSplit,
  onCancelTask,
  onOpenOutput,
  onRetryTask,
}: ClipSplitterPageProps) {
  // Mensagem de feedback da ultima acao (ex.: falta escolher o video).
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  const sourcePath = useAppStore((state) => state.clipSplitterSourcePath)
  const outputDir = useAppStore((state) => state.clipSplitterSettings.outputDir ?? null)
  const tasks = useAppStore((state) => state.clipSplitterTasks)
  const setSourcePath = useAppStore((state) => state.setClipSplitterSourcePath)
  const setOutputDir = useAppStore((state) => state.setClipSplitterOutputDir)

  // Roda uma acao assincrona e mostra a mensagem que ela devolver.
  async function runAction(action: () => Promise<ActionResult>) {
    const result = await action()
    setActionMessage(result.message)
  }

  return (
    <Workspace description={description} inspector={<PreEditInspector />} title={title}>
      <SourceCard
        message={actionMessage}
        onDropSource={(path) => {
          setActionMessage(null)
          setSourcePath(path)
        }}
        onPickOutputDir={() => void runAction(onPickOutputDir)}
        onPickSource={() => void runAction(onPickSourceFile)}
        onResetOutputDir={() => setOutputDir(null)}
        onStart={() => void runAction(onStartSplit)}
        outputDir={outputDir}
        sourcePath={sourcePath}
      />
      <ClipSplitterTaskList onCancel={onCancelTask} onOpenOutput={onOpenOutput} onRetry={onRetryTask} tasks={tasks} />
    </Workspace>
  )
}
