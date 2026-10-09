import { startTransition, useEffectEvent } from 'react'
import { useEffect } from 'react'

import { burnNotice, subtitleNotice } from '@/lib/finishNotices'
import { notifyIfAway } from '@/lib/notify'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type {
  HardsubEvent,
  HardsubMode,
  SubtitleDoneEvent,
  SubtitleErrorEvent,
  SubtitleProgressEvent,
  SubtitleTaskOptions,
} from '@/types/subtitle'

const mediaFilters = [
  {
    name: 'Midia',
    extensions: ['mp4', 'mov', 'mkv', 'avi', 'webm', 'mp3', 'wav', 'm4a', 'aac', 'flac'],
  },
]

export interface QueueFilesResult {
  ok: boolean
  message: string | null
}

// Captura um snapshot da configuracao atual para enviar junto com cada nova tarefa.
function getSettingsSnapshot(): Partial<SubtitleTaskOptions> {
  return useAppStore.getState().subtitleSettings
}

export function useSubtitleForge() {
  // A API do preload e opcional para permitir que a UI ainda renderize fora do Electron.
  const clipForgeApi = typeof window !== 'undefined' ? window.clipforge : undefined

  // Cada handler traduz eventos do backend em atualizacoes da store global.
  const handleProgress = useEffectEvent((data: SubtitleProgressEvent) => {
    useAppStore.getState().upsertSubtitleProgress(data)
  })

  const handleDone = useEffectEvent((data: SubtitleDoneEvent) => {
    useAppStore.getState().completeSubtitleTask(data)
    notifyIfAway(subtitleNotice(data))
  })

  const handleError = useEffectEvent((data: SubtitleErrorEvent) => {
    useAppStore.getState().failSubtitleTask(data)
    notifyIfAway(subtitleNotice(data))
  })

  const handleBurnEvent = useEffectEvent((data: HardsubEvent) => {
    useAppStore.getState().upsertHardsubJob(data)
    // O evento da queima so traz o id da tarefa; o nome do arquivo vem da fila.
    const task = useAppStore.getState().subtitleTasks.find((item) => item.id === data.taskId)
    notifyIfAway(burnNotice(data, task?.fileName ?? 'Vídeo'))
  })

  useEffect(() => {
    // Registra os listeners uma unica vez enquanto a pagina estiver montada.
    if (!clipForgeApi?.subtitle) {
      console.error('[clipforge] preload API indisponivel no renderer')
      return
    }

    const offProgress = clipForgeApi.subtitle.onProgress((data) => handleProgress(data))
    const offDone = clipForgeApi.subtitle.onDone((data) => handleDone(data))
    const offError = clipForgeApi.subtitle.onError((data) => handleError(data))
    const offBurnProgress = clipForgeApi.subtitle.onBurnProgress((data) => handleBurnEvent(data))
    const offBurnDone = clipForgeApi.subtitle.onBurnDone((data) => handleBurnEvent(data))
    const offBurnError = clipForgeApi.subtitle.onBurnError((data) => handleBurnEvent(data))

    return () => {
      offProgress()
      offDone()
      offError()
      offBurnProgress()
      offBurnDone()
      offBurnError()
    }
  }, [clipForgeApi])

  // Converte arquivos vindos do navegador/drag and drop em caminhos absolutos.
  function resolvePathsFromFiles(files: FileList | null): string[] {
    if (!files) {
      return []
    }

    return Array.from(files)
      .map((file) => clipForgeApi?.dialog?.getPathForFile(file))
      .filter((path): path is string => Boolean(path))
  }

  // Enfileira um ou mais arquivos e cria o estado inicial das tasks no renderer.
  async function queuePaths(paths: string[]): Promise<QueueFilesResult> {
    const sanitizedPaths = Array.from(new Set(paths.filter(Boolean)))
    if (sanitizedPaths.length === 0) {
      return {
        ok: false,
        message: 'Nenhum arquivo valido foi encontrado.',
      }
    }

    if (!clipForgeApi?.subtitle) {
      console.error('[clipforge] subtitle API indisponivel para enfileirar arquivos')
      return {
        ok: false,
        message: 'A API desktop do ClipForge nao esta disponivel. Abra com npm.cmd run electron:dev.',
      }
    }

    const settings = getSettingsSnapshot()

    try {
      for (const filePath of sanitizedPaths) {
        const taskId = await clipForgeApi.subtitle.process(filePath, settings)

        startTransition(() => {
          useAppStore.getState().upsertSubtitleProgress({
            taskId,
            filePath,
            fileName: getFileName(filePath),
            model: settings.model ?? 'large-v3',
            language: settings.language ?? 'pt',
            device: settings.useCpu ? 'cpu' : 'cuda',
            status: 'queued',
            stage: 'queued',
            message: 'Tarefa adicionada a fila.',
            progress: null,
          })
        })
      }

      return {
        ok: true,
        message: null,
      }
    } catch (error) {
      console.error('[clipforge] falha ao enfileirar arquivo', error)
      return {
        ok: false,
        message: 'Nao foi possivel adicionar o arquivo a fila. Veja se o Electron e o backend estao ativos.',
      }
    }
  }

  // Reaproveita o fluxo de fila quando a entrada vier de um input de arquivos.
  async function queueFileSelection(files: FileList | null): Promise<QueueFilesResult> {
    if (!files || files.length === 0) {
      return {
        ok: false,
        message: 'Nenhum arquivo foi selecionado.',
      }
    }

    const paths = resolvePathsFromFiles(files)
    if (paths.length === 0) {
      return {
        ok: false,
        message: 'Nao foi possivel ler o caminho do arquivo selecionado.',
      }
    }

    return queuePaths(paths)
  }

  return {
    queuePaths,
    queueFileSelection,
    pickFiles: async (): Promise<QueueFilesResult> => {
      // Abre o seletor nativo do Electron e envia os arquivos escolhidos para a fila.
      if (!clipForgeApi?.dialog) {
        console.error('[clipforge] dialog API indisponivel para abrir arquivos')
        return {
          ok: false,
          message: 'O seletor de arquivos do Electron nao esta disponivel. Abra com npm.cmd run electron:dev.',
        }
      }

      const filePaths = await clipForgeApi.dialog.openFiles(mediaFilters)
      if (filePaths.length === 0) {
        return {
          ok: false,
          message: 'Nenhum arquivo foi selecionado.',
        }
      }

      return queuePaths(filePaths)
    },
    cancelTask: async (taskId: string) => {
      await clipForgeApi?.subtitle?.cancel(taskId)
    },
    openOutput: async (outputPath: string | null) => {
      // Revela o arquivo final no explorador apenas quando ja existe um caminho de saida.
      if (!outputPath) {
        return
      }

      await clipForgeApi?.shell?.showItemInFolder(outputPath)
    },
    retryTask: async (filePath: string) => {
      // Reprocessa o mesmo arquivo reaproveitando as configuracoes atuais da store.
      await queuePaths([filePath])
    },
    burnSubtitles: async (taskId: string, mode: HardsubMode) => {
      const format = useAppStore.getState().subtitleSettings.format
      await clipForgeApi?.subtitle?.burn(taskId, mode, format)
    },
  }
}
