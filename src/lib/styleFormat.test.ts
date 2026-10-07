import { describe, expect, it } from 'vitest'

import { describeTiming, formatF1, getProfileStatus } from '@/lib/styleFormat'
import type { StyleLibrary, StyleProfileParams } from '@/types/subtitleStyle'

const PARAMS: StyleProfileParams = {
  min_words: 2,
  max_words: 5,
  max_card_ms: 2000,
  lead_in_ms: 80.4,
  hold_ms: 249.6,
  glue_ms: 300,
  min_card_ms: 600,
  videos: 3,
  gap_examples: 900,
}

function library(videoProfiles: Array<'vertical' | 'horizontal'>, withModel: boolean): StyleLibrary {
  return {
    videos: videoProfiles.map((profile, index) => ({
      id: String(index),
      profile,
      name: `${index}.mp4`,
      originalPath: '',
      taughtAt: 0,
      f1Before: null,
      f1Formula: 0.5,
      gapExamples: 100,
      timingSamples: 30,
    })),
    profiles: withModel ? { vertical: { params: PARAMS, tree: '' } } : {},
    minVideos: 3,
  }
}

describe('formatF1', () => {
  it('mostra porcentagem inteira ou tracos', () => {
    expect(formatF1(0.724)).toBe('72%')
    expect(formatF1(1)).toBe('100%')
    expect(formatF1(null)).toBe('--')
    expect(formatF1(undefined)).toBe('--')
  })
})

describe('getProfileStatus', () => {
  it('conta videos do perfil e quanto falta pro minimo', () => {
    expect(getProfileStatus(library(['vertical', 'horizontal'], true), 'vertical')).toEqual({ videos: 1, remaining: 2, active: false })
  })

  it('so fica ativo com modelo e com o minimo de videos', () => {
    expect(getProfileStatus(library(['vertical', 'vertical', 'vertical'], true), 'vertical')).toEqual({ videos: 3, remaining: 0, active: true })
    expect(getProfileStatus(library(['vertical', 'vertical', 'vertical'], false), 'vertical').active).toBe(false)
    expect(getProfileStatus(null, 'horizontal')).toEqual({ videos: 0, remaining: 3, active: false })
  })
})

describe('describeTiming', () => {
  it('resume os tempos aprendidos em portugues', () => {
    expect(describeTiming(PARAMS)).toBe('Entra 80 ms antes da fala · segura 250 ms depois · cola buracos de até 300 ms · 2 a 5 palavras')
  })
})
