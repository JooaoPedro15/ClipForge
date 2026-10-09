import { describe, expect, test } from 'vitest'

import { formatDuration, summarizeQueue } from '@/lib/utils'

describe('formatDuration', () => {
  test('mantem o formato curto de antes', () => {
    expect(formatDuration(null)).toBe('--')
    expect(formatDuration(41.3)).toBe('41.3s')
    expect(formatDuration(125)).toBe('2m 5s')
  })

  test('video longo mostra horas', () => {
    expect(formatDuration(11_520)).toBe('3h 12m')
    expect(formatDuration(3_600)).toBe('1h 0m')
  })
})

describe('summarizeQueue', () => {
  test('conta por estado e pula o que esta zerado', () => {
    expect(
      summarizeQueue([{ status: 'processing' }, { status: 'queued' }, { status: 'queued' }, { status: 'completed' }]),
    ).toBe('1 rodando, 2 esperando, 1 pronta')
    expect(summarizeQueue([{ status: 'completed' }, { status: 'completed' }])).toBe('2 prontas')
    expect(summarizeQueue([])).toBe('')
  })
})
