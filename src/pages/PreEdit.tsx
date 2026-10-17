import { useState } from 'react'

import { Workspace } from '@/components/layout/Workspace'
import { PreeditInspector } from '@/components/preedit/PreeditInspector'
import { PreeditSourceCard } from '@/components/preedit/PreeditSourceCard'
import { PreeditTaskList } from '@/components/preedit/PreeditTaskList'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import type { useClipSplitter } from '@/hooks/useClipSplitter'
import type { PreeditActionResult, PreeditActions } from '@/hooks/usePreedit'
import { ClipSplitterPage } from '@/pages/ClipSplitter'
import { useAppStore } from '@/store/appStore'
import type { PreeditSettings } from '@/types/preedit'

interface PreEditPageProps {
  title: string
  description: string
  preedit: PreeditActions
  clipSplitter: ReturnType<typeof useClipSplitter>
}

const modeOptions: Array<{ value: PreeditSettings['mode']; label: string }> = [
  { value: 'learn', label: 'Que aprende' },
  { value: 'voice', label: 'Corte por voz' },
]

// Descricao do pre-editor antigo, que continua igual no modo "Corte por voz".
const VOICE_DESCRIPTION = 'Encurta as pausas do vídeo bruto e entrega uma versão única, na ordem original, pronta pra revisar.'

/**
 * Pre-edicao: no modo "Que aprende" solta os brutos de uma gravacao e recebe o XML com cortes e zooms
 * no jeito aprendido; "Corte por voz" e o pre-editor antigo, sem mudanca.
 */
export function PreEditPage({ title, description, preedit, clipSplitter }: PreEditPageProps) {
  const [message, setMessage] = useState<string | null>(null)
  const settings = useAppStore((state) => state.preeditSettings)
  const sources = useAppStore((state) => state.preeditSources)
  const tasks = useAppStore((state) => state.preeditTasks)
  const patchSettings = useAppStore((state) => state.patchPreeditSettings)

  const modeSwitch = (
    <SegmentedControl className="w-[240px]" label="modo da pré-edição" onChange={(mode) => patchSettings({ mode })} options={modeOptions} value={settings.mode} />
  )

  if (settings.mode === 'voice') {
    return (
      <ClipSplitterPage
        description={VOICE_DESCRIPTION}
        headerAction={modeSwitch}
        onCancelTask={clipSplitter.cancelTask}
        onOpenOutput={clipSplitter.openOutput}
        onPickOutputDir={clipSplitter.pickOutputDir}
        onPickSourceFile={clipSplitter.pickSourceFile}
        onRetryTask={clipSplitter.retryTask}
        onStartSplit={() => clipSplitter.startSplit()}
        title={title}
      />
    )
  }

  async function runAction(action: () => Promise<PreeditActionResult>) {
    setMessage((await action()).message)
  }

  return (
    <Workspace
      action={modeSwitch}
      description={description}
      inspector={
        <PreeditInspector
          onClearMolde={preedit.clearMolde}
          onPickMolde={() => void preedit.pickMolde()}
          onTeachFinals={preedit.teachFinals}
          onTeachProjects={preedit.teachProjects}
        />
      }
      title={title}
    >
      <PreeditSourceCard
        message={message}
        minutes={settings.minutes}
        onClearSources={() => {
          setMessage(null)
          preedit.clearSources()
        }}
        onDropSources={(paths) => {
          setMessage(null)
          preedit.dropSources(paths)
        }}
        onEdit={() => void runAction(preedit.edit)}
        onPickSources={() => void runAction(preedit.pickSources)}
        onRemoveSource={preedit.removeSource}
        sources={sources}
      />
      <PreeditTaskList onCancel={(taskId) => void preedit.cancelTask(taskId)} onOpenPath={(path) => void preedit.openPath(path)} onRetry={(task) => void runAction(() => preedit.retryTask(task))} tasks={tasks} />
    </Workspace>
  )
}
