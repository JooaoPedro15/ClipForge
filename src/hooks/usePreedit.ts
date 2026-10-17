import { startTransition, useEffect, useEffectEvent } from 'react'

import { notifyIfAway } from '@/lib/notify'
import { preeditNotice } from '@/lib/preeditSummary'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import { addSources } from '@/store/preeditState'
import type { PreeditJobRequest, PreeditTask, PreeditTaskEvent } from '@/types/preedit'

export interface PreeditActionResult {
  ok: boolean
  message: string | null
}

const videoFilters = [{ name: 'Vídeo', extensions: ['mp4', 'mkv', 'mov', 'm4v'] }]
const projectFilters = [{ name: 'Projeto do Premiere', extensions: ['prproj'] }]
const moldeFilters = [{ name: 'XML do Premiere', extensions: ['xml'] }]
const NO_BRIDGE = 'A API desktop da Pré-edição não está disponível. Abra com npm.cmd run electron:dev.'
const OK: PreeditActionResult = { ok: true, message: null }

// Titulo provisorio do item ate o primeiro evento chegar (o processo principal manda o mesmo).
function titleOf(job: PreeditJobRequest): string {
  if (job.kind === 'edit') {
    const [first = '', ...rest] = job.request.recordings
    return rest.length ? `${getFileName(first)} +${rest.length}` : getFileName(first)
  }
  if (job.kind === 'teach-projects') {
    const count = job.request.projects.length
    return `Ensinar com ${count} projeto${count === 1 ? '' : 's'}`
  }
  return 'Ensinar com vídeos prontos'
}

export function usePreedit() {
  // A API pode nao existir no navegador puro, por isso o acesso e defensivo.
  const api = typeof window !== 'undefined' ? window.clipforge : undefined

  async function refreshLibrary() {
    const result = await api?.preedit?.library()
    useAppStore.getState().setPreeditLibrary(result?.ok ? result.library : null)
  }

  const handleProgress = useEffectEvent((data: PreeditTaskEvent) => {
    useAppStore.getState().upsertPreeditEvent(data)
  })

  const handleFinished = useEffectEvent((data: PreeditTaskEvent) => {
    useAppStore.getState().upsertPreeditEvent(data)
    notifyIfAway(preeditNotice(data))
    if (data.kind !== 'edit' && data.status === 'completed') {
      void refreshLibrary()
    }
  })

  const loadLibrary = useEffectEvent(() => void refreshLibrary())

  useEffect(() => {
    if (!api?.preedit) {
      console.error('[clipforge] API da Pré-edição indisponível no renderer')
      return
    }
    loadLibrary()
    const offs = [
      api.preedit.onProgress((data) => handleProgress(data)),
      api.preedit.onDone((data) => handleFinished(data)),
      api.preedit.onError((data) => handleFinished(data)),
    ]
    return () => offs.forEach((off) => off())
  }, [api])

  // Manda o pedido pra fila; o item ganha o pedido pro "Tentar de novo".
  async function start(job: PreeditJobRequest): Promise<PreeditActionResult> {
    if (!api?.preedit) {
      return { ok: false, message: NO_BRIDGE }
    }
    try {
      const taskId =
        job.kind === 'edit'
          ? await api.preedit.edit(job.request)
          : job.kind === 'teach-projects'
            ? await api.preedit.teachProjects(job.request)
            : await api.preedit.teachFinals(job.request)
      startTransition(() => useAppStore.getState().attachPreeditRequest(taskId, titleOf(job), job))
      return OK
    } catch (error) {
      console.error('[clipforge] falha ao iniciar a Pré-edição', error)
      return { ok: false, message: 'Não deu pra começar agora. Verifique se o Electron está ativo.' }
    }
  }

  function dropSources(paths: string[]) {
    const store = useAppStore.getState()
    store.setPreeditSources(addSources(store.preeditSources, paths))
  }

  return {
    refreshLibrary,
    dropSources,
    pickSources: async (): Promise<PreeditActionResult> => {
      if (!api?.dialog) {
        return { ok: false, message: NO_BRIDGE }
      }
      dropSources(await api.dialog.openFiles(videoFilters))
      return OK
    },
    removeSource: (path: string) => {
      const store = useAppStore.getState()
      store.setPreeditSources(store.preeditSources.filter((source) => source !== path))
    },
    clearSources: () => useAppStore.getState().setPreeditSources([]),
    edit: async (): Promise<PreeditActionResult> => {
      const { preeditSources, preeditSettings } = useAppStore.getState()
      if (preeditSources.length === 0) {
        return { ok: false, message: 'Solte os brutos da gravação antes de gerar.' }
      }
      const { minutes, moldePath, zoomStyle } = preeditSettings
      return start({ kind: 'edit', request: { recordings: preeditSources, minutes, moldePath, zoomStyle } })
    },
    teachProjects: async (): Promise<PreeditActionResult> => {
      const projects = (await api?.dialog?.openFiles(projectFilters)) ?? []
      return projects.length ? start({ kind: 'teach-projects', request: { projects } }) : { ok: false, message: null }
    },
    teachFinals: async (): Promise<PreeditActionResult> => {
      const projectsDir = await api?.dialog?.openDirectory()
      if (!projectsDir) {
        return { ok: false, message: null }
      }
      const videosDir = await api?.dialog?.openDirectory()
      return videosDir ? start({ kind: 'teach-finals', request: { projectsDir, videosDir } }) : { ok: false, message: null }
    },
    retryTask: (task: PreeditTask): Promise<PreeditActionResult> =>
      task.request ? start(task.request) : Promise.resolve({ ok: false, message: 'Esse item não guardou o pedido; faça de novo pela tela.' }),
    cancelTask: async (taskId: string) => {
      await api?.preedit?.cancel(taskId)
    },
    openPath: async (filePath: string) => {
      await api?.shell?.showItemInFolder(filePath)
    },
    pickMolde: async () => {
      const [moldePath] = (await api?.dialog?.openFiles(moldeFilters)) ?? []
      if (moldePath) {
        useAppStore.getState().patchPreeditSettings({ moldePath })
      }
    },
    clearMolde: () => useAppStore.getState().patchPreeditSettings({ moldePath: '' }),
  }
}

export type PreeditActions = ReturnType<typeof usePreedit>
