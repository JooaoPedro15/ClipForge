import { Rail } from '@/components/layout/Rail'
import { Titlebar } from '@/components/layout/Titlebar'
import { useClipSplitter } from '@/hooks/useClipSplitter'
import { useSubtitleForge } from '@/hooks/useSubtitleForge'
import { getGpuStatus } from '@/lib/gpuStatus'
import { ClipSplitterPage } from '@/pages/ClipSplitter'
import { SubtitleForgePage } from '@/pages/SubtitleForge'
import { useAppStore } from '@/store/appStore'
import type { ToolId } from '@/types/subtitle'

export const pageMeta: Record<ToolId, { title: string; description: string }> = {
  'subtitle-forge': {
    title: 'Legendas',
    description: 'Solte um vídeo, ajuste no Inspetor e o .srt sai ao lado do arquivo original.',
  },
  'clip-splitter': {
    title: 'Pré-edição',
    description: 'Encurta as pausas do vídeo bruto e entrega uma versão única, na ordem original, pronta pra revisar.',
  },
}

export default function App() {
  const activeTool = useAppStore((state) => state.activeTool)
  const setActiveTool = useAppStore((state) => state.setActiveTool)
  const subtitleTasks = useAppStore((state) => state.subtitleTasks)
  const clipSplitterTasks = useAppStore((state) => state.clipSplitterTasks)
  const clipSplitter = useClipSplitter()
  const subtitleForge = useSubtitleForge()

  // As duas ferramentas dividem a mesma fila de GPU, entao o status e global.
  const gpu = getGpuStatus(
    subtitleTasks,
    clipSplitterTasks.map((task) => ({ fileName: task.sourceName, status: task.status })),
  )

  let content
  if (activeTool === 'clip-splitter') {
    content = (
      <ClipSplitterPage
        {...pageMeta['clip-splitter']}
        onCancelTask={clipSplitter.cancelTask}
        onOpenOutput={clipSplitter.openOutput}
        onPickOutputDir={clipSplitter.pickOutputDir}
        onPickSourceFile={clipSplitter.pickSourceFile}
        onRetryTask={clipSplitter.retryTask}
        onStartSplit={() => clipSplitter.startSplit()}
      />
    )
  } else {
    content = (
      <SubtitleForgePage
        {...pageMeta['subtitle-forge']}
        onBurn={subtitleForge.burnSubtitles}
        onCancelTask={subtitleForge.cancelTask}
        onDropPaths={subtitleForge.queuePaths}
        onOpenOutput={subtitleForge.openOutput}
        onPickFiles={subtitleForge.pickFiles}
        onRetryTask={subtitleForge.retryTask}
      />
    )
  }

  return (
    <div className="flex h-full flex-col bg-app text-text-primary">
      <Titlebar gpu={gpu} />
      <div className="flex min-h-0 flex-1">
        <Rail activeTool={activeTool} onSelect={setActiveTool} />
        <main className="min-w-0 flex-1">{content}</main>
      </div>
    </div>
  )
}
