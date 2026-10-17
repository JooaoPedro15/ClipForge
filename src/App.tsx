import { Rail } from '@/components/layout/Rail'
import { Titlebar } from '@/components/layout/Titlebar'
import { useClipSplitter } from '@/hooks/useClipSplitter'
import { useCortes } from '@/hooks/useCortes'
import { usePreedit } from '@/hooks/usePreedit'
import { useSubtitleForge } from '@/hooks/useSubtitleForge'
import { getGpuStatus, subtitleGpuEntries } from '@/lib/gpuStatus'
import { CortesPage } from '@/pages/Cortes'
import { PreEditPage } from '@/pages/PreEdit'
import { SubtitleForgePage } from '@/pages/SubtitleForge'
import { useAppStore } from '@/store/appStore'
import type { ToolId } from '@/types/subtitle'

export const pageMeta: Record<ToolId, { title: string; description: string }> = {
  'subtitle-forge': {
    title: 'Legendas',
    description: 'Legendar gera o .srt pra editar. Versão em chinês pega o vídeo pronto e devolve ele legendado em chinês.',
  },
  'clip-splitter': {
    title: 'Pré-edição',
    description: 'Solte os brutos da gravação: ele corta e dá zoom no seu jeito (aprendido com os seus projetos) e entrega um XML pro Premiere.',
  },
  cortes: {
    title: 'Cortes',
    description: 'Corta o react gravado em clipes pro TikTok e gera o XML do Premiere no layout do seu molde.',
  },
}

export default function App() {
  const activeTool = useAppStore((state) => state.activeTool)
  const setActiveTool = useAppStore((state) => state.setActiveTool)
  const subtitleTasks = useAppStore((state) => state.subtitleTasks)
  const clipSplitterTasks = useAppStore((state) => state.clipSplitterTasks)
  const cortesTasks = useAppStore((state) => state.cortesTasks)
  const preeditTasks = useAppStore((state) => state.preeditTasks)
  const clipSplitter = useClipSplitter()
  const subtitleForge = useSubtitleForge()
  const cortes = useCortes()
  const preedit = usePreedit()

  // As ferramentas dividem a mesma fila de GPU, entao o status e global.
  const gpu = getGpuStatus(
    subtitleGpuEntries(subtitleTasks),
    clipSplitterTasks.map((task) => ({ fileName: task.sourceName, status: task.status })),
    cortesTasks.map((task) => ({ fileName: task.sourceName, status: task.status })),
    preeditTasks.map((task) => ({ fileName: task.title, status: task.status })),
  )

  let content
  if (activeTool === 'clip-splitter') {
    content = <PreEditPage {...pageMeta['clip-splitter']} clipSplitter={clipSplitter} preedit={preedit} />
  } else if (activeTool === 'cortes') {
    content = (
      <CortesPage
        {...pageMeta.cortes}
        onAnalyze={cortes.analyze}
        onCancelTask={cortes.cancelTask}
        onDropSource={cortes.chooseSource}
        onGenerateXml={cortes.generateXml}
        onOpenPath={cortes.openPath}
        onPickSource={cortes.pickSource}
        onPickTemplate={cortes.pickTemplate}
        onResegment={cortes.resegment}
        onRetryTask={cortes.retryTask}
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
