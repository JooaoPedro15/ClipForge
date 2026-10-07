import { useCallback, useEffect, useState } from 'react'

import type { StyleLearnRequest, StyleLibrary, StyleProgressEvent, StyleReport } from '@/types/subtitleStyle'

// Estado do painel "Meu estilo": biblioteca, progresso do ensino em andamento e ultimo resultado.
export function useSubtitleStyle() {
  // A API do preload e opcional pra UI ainda renderizar fora do Electron (Vite puro).
  const api = typeof window !== 'undefined' ? window.clipforge?.subtitleStyle : undefined
  const [library, setLibrary] = useState<StyleLibrary | null>(null)
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<StyleProgressEvent | null>(null)
  const [report, setReport] = useState<StyleReport | null>(null)
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
      setProgress(null)
      try {
        const result = await api.learn(request)
        if (result.ok) {
          setReport(result.report)
        } else {
          setError(result.error)
        }
        await refresh()
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

  return { available: Boolean(api), library, running, progress, report, error, learn, forget }
}
