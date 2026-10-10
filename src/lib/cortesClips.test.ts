import { describe, expect, test } from 'vitest'

import { cortesStep, formatClock, isClockText, sameDurations, topClips } from '@/lib/cortesClips'
import type { CortesClip } from '@/types/cortes'

const clip = (n: number, score: number | null): CortesClip => ({ n, start: 0, end: 1, title: '', hook: null, score })

describe('cortesStep', () => {
  test('etapas da analise em 4 passos; juiz conta como Cortes', () => {
    expect(cortesStep('extracting')).toEqual({ index: 1, label: 'Leitura' })
    expect(cortesStep('transcribing')).toEqual({ index: 2, label: 'Transcrição' })
    expect(cortesStep('choosing')).toEqual({ index: 3, label: 'Cortes' })
    expect(cortesStep('judging')).toEqual({ index: 3, label: 'Cortes' })
    expect(cortesStep('titling')).toEqual({ index: 4, label: 'Títulos' })
    expect(cortesStep('queued')).toBeNull()
  })
})

describe('topClips', () => {
  test('os N de maior nota, devolvidos na ordem do filme', () => {
    expect(topClips([clip(1, 3), clip(2, null), clip(3, 9), clip(4, 7)], 2)).toEqual([3, 4])
  })

  test('sem nota fica por ultimo e N maior que a lista pega todos', () => {
    expect(topClips([clip(1, null), clip(2, 5)], 1)).toEqual([2])
    expect(topClips([clip(1, null), clip(2, 5)], 5)).toEqual([1, 2])
  })

  test('zero ou negativo nao marca nada', () => {
    expect(topClips([clip(1, 5)], 0)).toEqual([])
    expect(topClips([clip(1, 5)], -2)).toEqual([])
  })
})

describe('formatClock', () => {
  test('minutos ou horas, sem casas decimais', () => {
    expect(formatClock(144.44)).toBe('2:24')
    expect(formatClock(59.9)).toBe('0:59')
    expect(formatClock(3723)).toBe('1:02:03')
  })
})

describe('isClockText', () => {
  test('aceita o que o Python aceita e vazio', () => {
    for (const text of ['', ' ', '95.5', '2:24', '2:24,44', '1:58:00']) {
      expect(isClockText(text)).toBe(true)
    }
  })

  test('recusa texto que o Python nao entende', () => {
    for (const text of ['2m24', '1:2:3:4', ':30', '2:', 'abc', '1.5:20']) {
      expect(isClockText(text)).toBe(false)
    }
  })
})

describe('sameDurations', () => {
  test('compara as tres duracoes', () => {
    const base = { minSec: 70, targetSec: 150, maxSec: 240 }
    expect(sameDurations(base, { ...base })).toBe(true)
    expect(sameDurations(base, { ...base, minSec: 60 })).toBe(false)
  })
})
