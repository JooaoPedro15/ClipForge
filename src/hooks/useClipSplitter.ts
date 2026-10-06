import { startTransition, useEffectEvent } from 'react'
import { useEffect } from 'react'

import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type {
  ClipFeedbackLabel,
  ClipSplitterClip,
  ClipSplitterDoneEvent,
  ClipSplitterErrorEvent,
  ClipSplitterOptions,
  ClipSplitterProgressEvent,
} from '@/types/clipSplitter'

const videoFilters = [
  {
    name: 'Video',
    extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm', 'm4v'],
  },
]

export interface ClipSplitterActionResult {
  ok: boolean
  message: string | null
}

// Le a configuracao atual do Pre-Editor sem depender do ciclo de renderizacao.
function getSettingsSnapshot(): Partial<ClipSplitterOptions> {
  return useAppStore.getState().clipSplitterSettings
}

export function useClipSplitter() {
  // A API pode nao existir no navegador puro, por isso o acesso e defensivo.
  const clipForgeApi = typeof window !== 'undefined' ? window.clipforge : undefined

  // Sincroniza os eventos do processo Python/Electron com a store global do app.
  const handleProgress = useEffectEvent((data: ClipSplitterProgressEvent) => {
    useAppStore.getState().upsertClipSplitterProgress(data)
  })

  const handleDone = useEffectEvent((data: ClipSplitterDoneEvent) => {
    useAppStore.getState().completeClipSplitterTask(data)
  })

  const handleError = useEffectEvent((data: ClipSplitterErrorEvent) => {
    useAppStore.getState().failClipSplitterTask(data)
  })

  useEffect(() => {
    // Assina progresso, conclusao e erro enquanto o hook estiver ativo.
    if (!clipForgeApi?.clipSplitter) {
      console.error('[clipforge] Pre-Editor API indisponivel no renderer')
      return
    }

    const offProgress = clipForgeApi.clipSplitter.onProgress((data) => handleProgress(data))
    const offDone = clipForgeApi.clipSplitter.onDone((data) => handleDone(data))
    const offError = clipForgeApi.clipSplitter.onError((data) => handleError(data))

    return () => {
      offProgress()
      offDone()
      offError()
    }
  }, [clipForgeApi, handleDone, handleError, handleProgress])

  // Mantem o caminho do video fonte compartilhado entre os componentes da pagina.
  function setSourcePath(sourcePath: string | null) {
    useAppStore.getState().setClipSplitterSourcePath(sourcePath)
  }

  // Dispara um novo job de corte usando a configuracao atual salva na store.
  async function startSplit(sourcePath?: string | null): Promise<ClipSplitterActionResult> {
    const resolvedSourcePath = sourcePath ?? useAppStore.getState().clipSplitterSourcePath
    if (!resolvedSourcePath) {
      return {
        ok: false,
        message: 'Selecione um video antes de gerar a pre-edicao.',
      }
    }

    if (!clipForgeApi?.clipSplitter) {
      return {
        ok: false,
        message: 'A API desktop do Pre-Editor nao esta disponivel. Abra com npm.cmd run electron:dev.',
      }
    }

    const settings = getSettingsSnapshot()

    try {
      const taskId = await clipForgeApi.clipSplitter.process(resolvedSourcePath, settings)

      startTransition(() => {
        useAppStore.getState().upsertClipSplitterProgress({
          taskId,
          sourcePath: resolvedSourcePath,
          sourceName: getFileName(resolvedSourcePath),
          mode: settings.mode ?? 'silence',
          status: 'queued',
          stage: 'queued',
          message: 'Job adicionado a fila de pre-edicao.',
          progress: null,
          outputDir: settings.outputDir ?? null,
        })
      })

      return {
        ok: true,
        message: null,
      }
    } catch (error) {
      console.error('[clipforge] falha ao iniciar Pre-Editor', error)
      return {
        ok: false,
        message: 'Nao foi possivel iniciar a pre-edicao agora. Verifique se o Electron esta ativo.',
      }
    }
  }

  return {
    pickSourceFile: async (): Promise<ClipSplitterActionResult> => {
      // Abre o seletor nativo e guarda o primeiro video escolhido como fonte atual.
      if (!clipForgeApi?.dialog) {
        return {
          ok: false,
          message: 'O seletor de arquivos do Electron nao esta disponivel. Abra com npm.cmd run electron:dev.',
        }
      }

      const selectedPaths = await clipForgeApi.dialog.openFiles(videoFilters)
      const sourcePath = selectedPaths[0] ?? null
      if (!sourcePath) {
        return {
          ok: false,
          message: 'Nenhum video foi selecionado.',
        }
      }

      setSourcePath(sourcePath)
      return {
        ok: true,
        message: null,
      }
    },
    pickOutputDir: async (): Promise<ClipSplitterActionResult> => {
      // Permite sobrescrever a pasta de saida padrao antes de exportar a pre-edicao.
      if (!clipForgeApi?.dialog?.openDirectory) {
        return {
          ok: false,
          message: 'A selecao de pasta nao esta disponivel nesta execucao.',
        }
      }

      const outputDir = await clipForgeApi.dialog.openDirectory()
      if (!outputDir) {
        return {
          ok: false,
          message: 'Nenhuma pasta de saida foi selecionada.',
        }
      }

      useAppStore.getState().setClipSplitterOutputDir(outputDir)
      return {
        ok: true,
        message: null,
      }
    },
    setSourcePath,
    startSplit,
    cancelTask: async (taskId: string) => {
      await clipForgeApi?.clipSplitter?.cancel(taskId)
    },
    openOutput: async (outputDir: string | null) => {
      // Abre a pasta ou arquivo relacionado ao corte exportado.
      if (!outputDir) {
        return
      }

      await clipForgeApi?.shell?.showItemInFolder(outputDir)
    },
    retryTask: async (sourcePath: string) => {
      // Reusa o mesmo video como fonte e inicia um novo job.
      setSourcePath(sourcePath)
      return startSplit(sourcePath)
    },
    saveClipFeedback: async (taskId: string, clip: ClipSplitterClip, label: ClipFeedbackLabel | null) => {
      // Persiste o feedback manual para alimentar cortes futuros com memoria local.
      if (!clipForgeApi?.clipSplitter?.saveFeedback) {
        return {
          ok: false,
          message: 'A API de feedback do Pre-Editor nao esta disponivel nesta execucao.',
        }
      }

      try {
        const saved = await clipForgeApi.clipSplitter.saveFeedback(clip, label)
        if (!saved) {
          return {
            ok: false,
            message: 'Nao foi possivel salvar o feedback deste clipe.',
          }
        }

        // Atualiza a UI imediatamente sem esperar um novo ciclo de sincronizacao.
        useAppStore.getState().setClipFeedbackForTask(taskId, clip.clipId, label)
        return {
          ok: true,
          message: null,
        }
      } catch (error) {
        console.error('[clipforge] falha ao salvar feedback do clip', error)
        return {
          ok: false,
          message: 'Falha ao salvar feedback local do clipe.',
        }
      }
    },
  }
}
