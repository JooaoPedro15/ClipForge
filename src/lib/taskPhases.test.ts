import { describe, expect, test } from 'vitest'

import { autoBurnPhase, effectiveStatus } from '@/lib/taskPhases'
import type { HardsubJobState, SubtitleTask } from '@/types/subtitle'

function task(overrides: Partial<SubtitleTask> = {}): SubtitleTask {
  return {
    id: 't1',
    filePath: 'D:\\final.mp4',
    fileName: 'final.mp4',
    outputPath: null,
    model: 'large-v3',
    language: 'pt',
    detectedLanguage: null,
    device: 'cuda',
    status: 'processing',
    stage: 'segments',
    message: '25 segmentos processados.',
    progress: 40,
    queuePosition: null,
    processedSegments: 25,
    totalSegments: null,
    createdAt: 0,
    startedAt: null,
    completedAt: null,
    durationSec: null,
    error: null,
    translatedOutputs: {},
    translationErrors: {},
    hardsubJobs: {},
    autoBurn: 'zh',
    ...overrides,
  }
}

const job = (overrides: Partial<HardsubJobState>): HardsubJobState => ({
  status: 'processing',
  stage: 'burning',
  message: 'Queimando legenda... 50%',
  progress: 50,
  outputPath: null,
  error: null,
  ...overrides,
})

describe('autoBurnPhase', () => {
  test('so legendar nao tem etapas', () => {
    expect(autoBurnPhase(task({ autoBurn: null }))).toBeNull()
  })

  test('etapa 1 enquanto transcreve', () => {
    expect(autoBurnPhase(task())).toMatchObject({ step: { index: 1, label: 'Transcrição' }, status: 'processing', progress: 40 })
  })

  test('legenda pronta e queima ainda nao chegou: etapa 2 esperando', () => {
    expect(autoBurnPhase(task({ status: 'completed', progress: 100 }))).toMatchObject({
      step: { index: 2, label: 'Tradução e queima' },
      status: 'queued',
    })
  })

  test('etapa 2 segue o progresso da queima', () => {
    const phase = autoBurnPhase(task({ status: 'completed', hardsubJobs: { zh: job({}) } }))
    expect(phase).toMatchObject({ step: { index: 2 }, status: 'processing', progress: 50, message: 'Queimando legenda... 50%' })
  })

  test('so termina quando o video em chines sai', () => {
    const phase = autoBurnPhase(task({ status: 'completed', hardsubJobs: { zh: job({ status: 'completed', progress: 100, outputPath: 'D:\\final.hardsub.zh.mp4' }) } }))
    expect(phase).toMatchObject({ step: null, status: 'completed', message: 'Vídeo em chinês pronto, ao lado do original.' })
  })

  test('erro na queima vira erro da tarefa', () => {
    const phase = autoBurnPhase(task({ status: 'completed', hardsubJobs: { zh: job({ status: 'error', error: 'validacao reprovou' }) } }))
    expect(phase).toMatchObject({ status: 'error', step: null })
  })
})

describe('effectiveStatus', () => {
  test('legenda pronta com queima rodando ainda conta como rodando', () => {
    expect(effectiveStatus(task({ status: 'completed', hardsubJobs: { zh: job({}) } }))).toBe('processing')
    expect(effectiveStatus(task({ status: 'completed', autoBurn: null }))).toBe('completed')
  })
})
