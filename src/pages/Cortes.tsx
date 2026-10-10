import { useState } from 'react'

import { CortesInspector } from '@/components/cortes/CortesInspector'
import { CortesSourceCard } from '@/components/cortes/CortesSourceCard'
import { CortesTaskList } from '@/components/cortes/CortesTaskList'
import { Workspace } from '@/components/layout/Workspace'
import type { CortesActionResult, CortesRange } from '@/hooks/useCortes'
import { useAppStore } from '@/store/appStore'
import type { CortesTask } from '@/types/cortes'

interface CortesPageProps {
  title: string
  description: string
  onPickSource: () => Promise<CortesActionResult>
  onDropSource: (path: string) => Promise<void>
  onAnalyze: (range: CortesRange) => Promise<CortesActionResult>
  onCancelTask: (taskId: string) => void
  onRetryTask: (task: CortesTask) => Promise<CortesActionResult>
  onResegment: (task: CortesTask) => Promise<CortesActionResult>
  onGenerateXml: (task: CortesTask, clips: number[]) => void
  onOpenPath: (path: string) => void
  onPickTemplate: () => void
}

const EMPTY_RANGE: CortesRange = { start: '', end: '' }

/**
 * Pagina dos Cortes: solta o bruto do react, acompanha as 4 etapas na fila,
 * marca os clipes e gera o XML do Premiere. O molde e as duracoes ficam no Inspetor.
 */
export function CortesPage({
  title,
  description,
  onPickSource,
  onDropSource,
  onAnalyze,
  onCancelTask,
  onRetryTask,
  onResegment,
  onGenerateXml,
  onOpenPath,
  onPickTemplate,
}: CortesPageProps) {
  // Mensagem da ultima acao (ex.: trecho invalido) e o trecho, que vale so pro bruto atual.
  const [message, setMessage] = useState<string | null>(null)
  const [range, setRange] = useState<CortesRange>(EMPTY_RANGE)

  const sourcePath = useAppStore((state) => state.cortesSourcePath)
  const tasks = useAppStore((state) => state.cortesTasks)
  const settings = useAppStore((state) => state.cortesSettings)

  async function runAction(action: () => Promise<CortesActionResult>) {
    const result = await action()
    setMessage(result.message)
    return result
  }

  return (
    <Workspace description={description} inspector={<CortesInspector onPickTemplate={onPickTemplate} />} title={title}>
      <CortesSourceCard
        message={message}
        onAnalyze={() => void runAction(() => onAnalyze(range))}
        onDropSource={(path) => {
          setMessage(null)
          setRange(EMPTY_RANGE)
          void onDropSource(path)
        }}
        onPickSource={() =>
          void runAction(onPickSource).then((result) => {
            if (result.ok) {
              setRange(EMPTY_RANGE)
            }
          })
        }
        onRangeChange={setRange}
        range={range}
        sourcePath={sourcePath}
      />
      <CortesTaskList
        durations={{ minSec: settings.minSec, targetSec: settings.targetSec, maxSec: settings.maxSec }}
        onCancel={onCancelTask}
        onGenerateXml={onGenerateXml}
        onOpenPath={onOpenPath}
        onResegment={(task) => void runAction(() => onResegment(task))}
        onRetry={(task) => void runAction(() => onRetryTask(task))}
        tasks={tasks}
        templatePath={settings.templatePath}
      />
    </Workspace>
  )
}
