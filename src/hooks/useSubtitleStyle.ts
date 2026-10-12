import { useCallback, useEffect, useState } from 'react'

import type {
  StyleLearnRequest,
  StyleLibrary,
  StyleProgressEvent,
  StyleProjectLearnReport,
  StyleProjectLearnRequest,
  StyleProjectScan,
  StyleReport,
} from '@/types/subtitleStyle'

// Chamada que nem chegou ao Python: o caso tipico e o processo principal antigo (app aberto antes de
// atualizar), sem o canal novo. Sem isto a tela so ficava parada, sem dizer nada.
function describeFailure(caught: unknown) {
  const detail = caught instanceof Error ? caught.message : String(caught)
  return `Falha ao falar com o app (${detail}). Se o app foi atualizado, feche e abra de novo.`
}

// Estado do painel "Meu estilo": biblioteca, progresso do ensino em andamento e ultimo resultado.
export function useSubtitleStyle() {
  // A API do preload e opcional pra UI ainda renderizar fora do Electron (Vite puro).
  const api = typeof window !== 'undefined' ? window.clipforge?.subtitleStyle : undefined
  const [library, setLibrary] = useState<StyleLibrary | null>(null)
  const [running, setRunning] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [progress, setProgress] = useState<StyleProgressEvent | null>(null)
  const [report, setReport] = useState<StyleReport | null>(null)
  const [batchReport, setBatchReport] = useState<StyleProjectLearnReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (api) {
      setLibrary(await api.list())
    }
  }, [api])

  useEffect(() => {
    if (!api) {
      return
    }
    // `active` evita atualizar estado depois que o painel saiu da tela.
    let active = true
    void api.list().then((next) => {
      if (active) {
        setLibrary(next)
      }
    })
    const offProgress = api.onProgress((event) => setProgress(event))
    return () => {
      active = false
      offProgress()
    }
  }, [api])

  const learn = useCallback(
    async (request: StyleLearnRequest) => {
      if (!api) {
        return
      }
      setRunning(true)
      setError(null)
      setReport(null)
      setBatchReport(null)
      setProgress(null)
      try {
        const result = await api.learn(request)
        if (result.ok) {
          setReport(result.report)
        } else {
          setError(result.error)
        }
        await refresh()
      } catch (caught) {
        setError(describeFailure(caught))
      } finally {
        setRunning(false)
      }
    },
    [api, refresh],
  )

  const forget = useCallback(
    async (videoId: string) => {
      if (!api) {
        return
      }
      const result = await api.forget(videoId)
      setError(result.ok ? null : result.error)
      await refresh()
    },
    [api, refresh],
  )

  // Ensina todas as sequencias completas do projeto de uma vez.
  const learnProject = useCallback(
    async (request: StyleProjectLearnRequest) => {
      if (!api) {
        return
      }
      setRunning(true)
      setError(null)
      setReport(null)
      setBatchReport(null)
      setProgress(null)
      try {
        const result = await api.learnProject(request)
        if (result.ok) {
          setBatchReport(result.report)
        } else {
          setError(result.error)
        }
        await refresh()
      } catch (caught) {
        setError(describeFailure(caught))
      } finally {
        setRunning(false)
      }
    },
    [api, refresh],
  )

  // Lista as sequencias com legenda de um projeto do Premiere (null = erro, mostrado em `error`).
  const scanProject = useCallback(
    async (projectPath: string, originalsDir?: string | null): Promise<StyleProjectScan | null> => {
      if (!api) {
        return null
      }
      setScanning(true)
      setError(null)
      try {
        const result = await api.scanProject(projectPath, originalsDir)
        if (result.ok) {
          return result.report
        }
        setError(result.error)
        return null
      } catch (caught) {
        setError(describeFailure(caught))
        return null
      } finally {
        setScanning(false)
      }
    },
    [api],
  )

  return {
    available: Boolean(api),
    library,
    running,
    scanning,
    progress,
    report,
    batchReport,
    error,
    learn,
    learnProject,
    forget,
    scanProject,
  }
}
