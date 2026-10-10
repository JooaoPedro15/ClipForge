import { startTransition, useEffect, useEffectEvent } from 'react'

import { isClockText } from '@/lib/cortesClips'
import { cortesNotice } from '@/lib/finishNotices'
import { notifyIfAway } from '@/lib/notify'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import { loadedCortesTask } from '@/store/cortesTasks'
import type { CortesAnalyzeOptions, CortesDoneEvent, CortesErrorEvent, CortesProgressEvent, CortesTask } from '@/types/cortes'

export interface CortesActionResult {
  ok: boolean
  message: string | null
}

export interface CortesRange {
  start: string
  end: string
}

const videoFilters = [{ name: 'Video', extensions: ['mp4', 'mov', 'mkv', 'm4v'] }]
const templateFilters = [{ name: 'XML do Premiere', extensions: ['xml'] }]
const NO_BRIDGE = 'A API desktop dos Cortes não está disponível. Abra com npm.cmd run electron:dev.'
const OK: CortesActionResult = { ok: true, message: null }

// Opcoes do Inspetor no momento do clique, mais o trecho digitado no cartao.
function analyzeOptions(range: CortesRange): CortesAnalyzeOptions {
  const settings = useAppStore.getState().cortesSettings
  return {
    start: range.start.trim(),
    end: range.end.trim(),
    filmTrack: settings.filmTrack,
    micTrack: settings.micTrack,
    minSec: settings.minSec,
    targetSec: settings.targetSec,
    maxSec: settings.maxSec,
    titlesWithAi: settings.titlesWithAi,
  }
}

export function useCortes() {
  // A API pode nao existir no navegador puro, por isso o acesso e defensivo.
  const api = typeof window !== 'undefined' ? window.clipforge : undefined

  const handleProgress = useEffectEvent((data: CortesProgressEvent) => {
    useAppStore.getState().upsertCortesEvent(data)
  })

  const handleFinished = useEffectEvent((data: CortesDoneEvent | CortesErrorEvent) => {
    useAppStore.getState().upsertCortesEvent(data)
    notifyIfAway(cortesNotice(data))
  })

  useEffect(() => {
    if (!api?.cortes) {
      console.error('[clipforge] API dos Cortes indisponivel no renderer')
      return
    }

    const offs = [
      api.cortes.onProgress((data) => handleProgress(data)),
      api.cortes.onDone((data) => handleFinished(data)),
      api.cortes.onError((data) => handleFinished(data)),
    ]
    return () => offs.forEach((off) => off())
  }, [api])

  // Bruto novo: se ja tem <bruto>.cortes.json ao lado, o item pronto entra direto na fila.
  async function chooseSource(sourcePath: string) {
    useAppStore.getState().setCortesSourcePath(sourcePath)
    const summary = await api?.cortes?.load(sourcePath)
    if (summary) {
      useAppStore.getState().addLoadedCortesTask(loadedCortesTask(crypto.randomUUID(), sourcePath, summary))
    }
  }

  async function startAnalysis(sourcePath: string, options: CortesAnalyzeOptions): Promise<CortesActionResult> {
    if (!isClockText(options.start) || !isClockText(options.end)) {
      return { ok: false, message: 'Trecho inválido. Use minutos:segundos, ex.: 2:24 ou 1:58:00.' }
    }
    if (!api?.cortes) {
      return { ok: false, message: NO_BRIDGE }
    }

    try {
      const taskId = await api.cortes.analyze(sourcePath, options)
      startTransition(() => {
        useAppStore.getState().startCortesEvent(
          {
            taskId,
            kind: 'analyze',
            sourcePath,
            sourceName: getFileName(sourcePath),
            status: 'queued',
            stage: 'queued',
            message: 'Na fila.',
            progress: null,
          },
          options,
        )
      })
      return OK
    } catch (error) {
      console.error('[clipforge] falha ao iniciar os Cortes', error)
      return { ok: false, message: 'Não deu pra começar a análise agora. Verifique se o Electron está ativo.' }
    }
  }

  async function resegment(task: CortesTask): Promise<CortesActionResult> {
    if (!task.analysis) {
      return { ok: false, message: 'Esse item ainda não tem análise.' }
    }
    if (!api?.cortes) {
      return { ok: false, message: NO_BRIDGE }
    }

    const settings = useAppStore.getState().cortesSettings
    const accepted = await api.cortes.resegment(task.id, {
      sourcePath: task.sourcePath,
      analysisPath: task.analysis.analysisPath,
      minSec: settings.minSec,
      targetSec: settings.targetSec,
      maxSec: settings.maxSec,
      titlesWithAi: settings.titlesWithAi,
    })
    return accepted ? OK : { ok: false, message: 'Esse item já está rodando.' }
  }

  return {
    chooseSource,
    pickSource: async (): Promise<CortesActionResult> => {
      if (!api?.dialog) {
        return { ok: false, message: NO_BRIDGE }
      }
      const [sourcePath] = await api.dialog.openFiles(videoFilters)
      if (!sourcePath) {
        return { ok: false, message: null }
      }
      await chooseSource(sourcePath)
      return OK
    },
    analyze: async (range: CortesRange): Promise<CortesActionResult> => {
      const sourcePath = useAppStore.getState().cortesSourcePath
      if (!sourcePath) {
        return { ok: false, message: 'Escolha o bruto do react antes de analisar.' }
      }
      return startAnalysis(sourcePath, analyzeOptions(range))
    },
    resegment,
    retryTask: async (task: CortesTask): Promise<CortesActionResult> =>
      task.kind === 'resegment' ? resegment(task) : startAnalysis(task.sourcePath, task.request ?? analyzeOptions({ start: '', end: '' })),
    cancelTask: async (taskId: string) => {
      await api?.cortes?.cancel(taskId)
    },
    // Gerar XML nao passa pela fila de GPU: o estado fica no proprio item.
    generateXml: async (task: CortesTask, clips: number[]) => {
      const store = useAppStore.getState()
      if (!task.analysis || !api?.cortes) {
        return
      }
      store.setCortesXml(task.id, { status: 'running', outputPath: null, error: null })
      const result = await api.cortes.generateXml({
        analysisPath: task.analysis.analysisPath,
        templatePath: store.cortesSettings.templatePath,
        clips,
      })
      useAppStore
        .getState()
        .setCortesXml(task.id, result.ok ? { status: 'done', outputPath: result.outputPath, error: null } : { status: 'error', outputPath: null, error: result.error })
    },
    pickTemplate: async () => {
      const [templatePath] = (await api?.dialog?.openFiles(templateFilters)) ?? []
      if (templatePath) {
        useAppStore.getState().patchCortesSettings({ templatePath })
      }
    },
    openPath: async (filePath: string) => {
      await api?.shell?.showItemInFolder(filePath)
    },
  }
}
