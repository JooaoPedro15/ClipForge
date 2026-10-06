import { Sidebar } from '@/components/layout/Sidebar'
import { Topbar } from '@/components/layout/Topbar'
import { useClipSplitter } from '@/hooks/useClipSplitter'
import { useSubtitleForge } from '@/hooks/useSubtitleForge'
import { ClipSplitterPage } from '@/pages/ClipSplitter'
import { SubtitleForgePage } from '@/pages/SubtitleForge'
import { useAppStore } from '@/store/appStore'
import type { ToolId } from '@/types/subtitle'

export const pageMeta: Record<ToolId, { title: string; description: string }> = {
  'subtitle-forge': {
    title: 'SubtitleForge',
    description: 'Central de transcricao com fila, presets de legenda e integracao com o pipeline Python local.',
  },
  'clip-splitter': {
    title: 'Pre-Editor',
    description: 'Pre-edicao automatica do bruto: comprime pausas, preserva a ordem e mantem faixas separadas.',
  },
}

export default function App() {
  const activeTool = useAppStore((state) => state.activeTool)
  const setActiveTool = useAppStore((state) => state.setActiveTool)
  const clipSplitter = useClipSplitter()
  const subtitleForge = useSubtitleForge()

  let content
  if (activeTool === 'clip-splitter') {
    content = (
      <ClipSplitterPage
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
    <div className="min-h-screen bg-[linear-gradient(180deg,#080808_0%,#000000_100%)] px-5 py-5 text-text-primary">
      <div className="grid min-h-[calc(100vh-40px)] gap-5 xl:grid-cols-[280px_minmax(0,1fr)]">
        <Sidebar activeTool={activeTool} onSelect={setActiveTool} />

        <main className="flex min-h-0 flex-col gap-5">
          <Topbar description={pageMeta[activeTool].description} title={pageMeta[activeTool].title} />
          <section className="min-h-0 flex-1 overflow-y-auto rounded-2xl border border-white/6 bg-white/[0.025] p-5">
            {content}
          </section>
        </main>
      </div>
    </div>
  )
}
