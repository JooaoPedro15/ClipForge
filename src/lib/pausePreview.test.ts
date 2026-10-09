import { describe, expect, test } from 'vitest'

import { keptPauseSeconds, simulatePreEdit } from '@/lib/pausePreview'

describe('keptPauseSeconds', () => {
  test('pausa curta fica inteira', () => {
    expect(keptPauseSeconds('breathing_pause', 0.3, 'balanced')).toBe(0.3)
  })

  test('pausa longa e cortada no limite do tipo', () => {
    expect(keptPauseSeconds('dramatic_pause', 1.8, 'balanced')).toBe(0.75)
    expect(keptPauseSeconds('dramatic_pause', 1.8, 'conservative')).toBe(0.9)
  })

  test('forte remove silencio morto de 4s ou mais', () => {
    expect(keptPauseSeconds('dead_silence', 5, 'aggressive')).toBe(0)
    expect(keptPauseSeconds('dead_silence', 3, 'aggressive')).toBe(0.15)
  })
})

describe('simulatePreEdit', () => {
  test('quanto mais forte, mais curto fica o exemplo', () => {
    const light = simulatePreEdit('conservative').afterSec
    const balanced = simulatePreEdit('balanced').afterSec
    const strong = simulatePreEdit('aggressive').afterSec
    expect(light).toBeGreaterThan(balanced)
    expect(balanced).toBeGreaterThan(strong)
  })

  test('fala nunca e cortada', () => {
    const result = simulatePreEdit('aggressive')
    const speechBefore = result.blocks.filter((block) => block.kind === 'speech').reduce((sum, block) => sum + block.beforeSec, 0)
    const speechAfter = result.blocks.filter((block) => block.kind === 'speech').reduce((sum, block) => sum + block.afterSec, 0)
    expect(speechAfter).toBe(speechBefore)
  })
})
