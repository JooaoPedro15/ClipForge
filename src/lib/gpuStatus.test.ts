import { describe, expect, test } from 'vitest'

import { getGpuStatus, subtitleGpuEntries } from '@/lib/gpuStatus'

const base = { fileName: 'a.mp4', status: 'queued' as const }

describe('getGpuStatus', () => {
  test('livre quando nenhuma tarefa esta ativa', () => {
    expect(getGpuStatus([{ ...base, status: 'completed' }], [])).toEqual({ busyWith: null, queued: 0 })
  })

  test('aponta o arquivo em processamento em qualquer ferramenta', () => {
    const subtitle = [{ fileName: 'ep01.mp4', status: 'queued' as const }]
    const preEdit = [{ fileName: 'bruto.mkv', status: 'processing' as const }]
    expect(getGpuStatus(subtitle, preEdit)).toEqual({ busyWith: 'bruto.mkv', queued: 1 })
  })

  test('preparando tambem ocupa a gpu', () => {
    expect(getGpuStatus([{ fileName: 'ep02.mp4', status: 'preparing' as const }], [])).toEqual({
      busyWith: 'ep02.mp4',
      queued: 0,
    })
  })
})

describe('subtitleGpuEntries', () => {
  test('queima rodando ocupa a gpu mesmo com a legenda pronta', () => {
    const entries = subtitleGpuEntries([
      {
        fileName: 'ep01.mp4',
        status: 'completed' as const,
        hardsubJobs: { zh: { status: 'processing' as const, stage: 'burning', message: '', progress: 40, outputPath: null, error: null } },
      },
    ])
    expect(getGpuStatus(entries, [])).toEqual({ busyWith: 'ep01.mp4', queued: 0 })
  })
})
