import { describe, expect, test } from 'vitest'

import { burnNotice, preEditNotice, subtitleNotice } from '@/lib/finishNotices'
import type { ClipSplitterDoneEvent } from '@/types/clipSplitter'
import type { HardsubEvent, SubtitleDoneEvent, SubtitleErrorEvent } from '@/types/subtitle'

const subtitleBase = {
  taskId: 't1',
  filePath: 'D:\\ep01.mp4',
  fileName: 'ep01.mp4',
  model: 'large-v3' as const,
  language: 'pt',
  device: 'cuda' as const,
  stage: 'done',
  message: '',
}

describe('subtitleNotice', () => {
  test('legenda pronta com o tempo que levou', () => {
    const event: SubtitleDoneEvent = { ...subtitleBase, status: 'completed', progress: 100, completedAt: 1, durationSec: 41.3 }
    expect(subtitleNotice(event)).toEqual({ title: 'Legenda pronta', body: 'ep01.mp4 em 41.3s.' })
  })

  test('erro mostra so a primeira linha da mensagem', () => {
    const event: SubtitleErrorEvent = { ...subtitleBase, status: 'error', progress: null, error: 'CUDA out of memory\nTraceback...' }
    expect(subtitleNotice(event)).toEqual({ title: 'A legenda parou com erro', body: 'ep01.mp4: CUDA out of memory' })
  })

  test('cancelamento nao avisa: foi o proprio usuario', () => {
    const event: SubtitleErrorEvent = { ...subtitleBase, status: 'cancelled', progress: null, error: 'cancelado' }
    expect(subtitleNotice(event)).toBeNull()
  })
})

describe('burnNotice', () => {
  const burn = { taskId: 't1', jobId: 'j1', format: 'shorts' as const, stage: 'done', message: '', progress: 100 }

  test('queima pronta diz qual modo', () => {
    const event: HardsubEvent = { ...burn, mode: 'zh-en', status: 'completed' }
    expect(burnNotice(event, 'ep01.mp4')).toEqual({ title: 'Vídeo com legenda pronto', body: 'ep01.mp4: chinês + inglês.' })
  })

  test('traducao nova lembra de revisar antes de queimar', () => {
    const event: HardsubEvent = { ...burn, mode: 'translate-zh', status: 'completed' }
    expect(burnNotice(event, 'ep01.mp4')?.title).toBe('Tradução nova pronta')
  })

  test('progresso nao avisa', () => {
    expect(burnNotice({ ...burn, mode: 'zh', status: 'processing', progress: 40 }, 'ep01.mp4')).toBeNull()
  })
})

describe('preEditNotice', () => {
  test('mostra quanto o bruto encolheu', () => {
    const event: ClipSplitterDoneEvent = {
      taskId: 'p1',
      sourcePath: 'D:\\live.mkv',
      sourceName: 'live.mkv',
      mode: 'silence',
      status: 'completed',
      stage: 'done',
      message: '',
      progress: 100,
      completedAt: 1,
      durationSec: 600,
      sourceDurationSec: 11_520,
      clips: [{ clipId: 'c', index: 1, filePath: '', fileName: '', startSec: 0, endSec: 0, durationSec: 9_684, reason: '', transcriptSnippet: '' }],
    }
    expect(preEditNotice(event)).toEqual({ title: 'Pré-edição pronta', body: 'live.mkv: 3h 12m viraram 2h 41m.' })
  })
})
