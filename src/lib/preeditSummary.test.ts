import { describe, expect, test } from 'vitest'

import { editSummary, failureDetails, preeditNotice, teachSummary } from '@/lib/preeditSummary'

describe('teachSummary', () => {
  test('conta ensinados, pulados por motivo e falhas', () => {
    expect(teachSummary({ taught: [1, 2, 3, 4], skipped: [{ reason: 'ja ensinada' }, { reason: 'ja ensinada' }], failed: [{}] })).toBe(
      '4 ensinados, 2 pulados (ja ensinada), 1 falha',
    )
  })

  test('agrupa motivos sem o detalhe entre parenteses, o mais comum primeiro', () => {
    const skipped = [{ reason: 'sem zoom (Longo 1)' }, { reason: 'video exportado nao encontrado na pasta (S)' }, { reason: 'sem zoom (Longo 2)' }]
    expect(teachSummary({ taught: [1], skipped, failed: [] })).toBe('1 ensinado, 3 pulados (2 sem zoom, 1 video exportado nao encontrado na pasta)')
  })

  test('relatorio vazio', () => {
    expect(teachSummary({})).toBe('0 ensinados')
  })
})

describe('editSummary', () => {
  test('duracao final, trechos e zooms', () => {
    expect(editSummary({ durationSec: 750, segments: 48, zooms: 9 })).toBe('12 min 30 s, 48 trechos, 9 zooms')
    expect(editSummary({ durationSec: 59.6, segments: 1, zooms: 0 })).toBe('1 min, 1 trecho, sem zoom')
  })
})

describe('preeditNotice', () => {
  test('pronto, ensino e erro avisam; cancelado nao', () => {
    const base = { taskId: 't', title: 'A.mkv +1', stage: 'done', message: '', progress: 100, warnings: [] }
    expect(preeditNotice({ ...base, kind: 'edit', status: 'completed', result: { durationSec: 750, segments: 48, zooms: 9 } })).toEqual({
      title: 'Pré-edição pronta',
      body: 'A.mkv +1: 12 min 30 s, 48 trechos, 9 zooms',
    })
    expect(preeditNotice({ ...base, kind: 'teach-finals', status: 'completed', result: { taught: [1] } })?.title).toBe('Ensino concluído')
    expect(preeditNotice({ ...base, kind: 'edit', status: 'error', error: 'Molde invalido: x\nTraceback' })?.body).toBe('A.mkv +1: Molde invalido: x')
    expect(preeditNotice({ ...base, kind: 'edit', status: 'cancelled' })).toBeNull()
  })
})

describe('failureDetails', () => {
  test('junta os arquivos que falharam pelo mesmo motivo e mostra ate 3 motivos', () => {
    const memory = 'Placa de video sem memoria: feche outros programas que usam a GPU.'
    const failed = [
      { recording: 'D:/Bruto/a.mkv', error: memory },
      { recording: 'D:/Bruto/b.mkv', error: memory },
      { recording: 'D:/Projetos/proj.prproj', error: 'Nao consegui ler proj.prproj' },
    ]
    expect(failureDetails({ failed })).toEqual([`a.mkv, b.mkv: ${memory}`, 'proj.prproj: Nao consegui ler proj.prproj'])
    expect(failureDetails({})).toEqual([])
  })
})
