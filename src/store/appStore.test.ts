import { describe, expect, test } from 'vitest'

import { useAppStore } from '@/store/appStore'

describe('clip splitter settings', () => {
  test('uses the second audio track as the default voice analysis track', () => {
    expect(useAppStore.getState().clipSplitterSettings.analysisAudioTrack).toBe('1')
  })
})

describe('subtitle settings', () => {
  test('usa o estilo aprendido por padrao (so tem efeito quando o perfil estiver pronto)', () => {
    expect(useAppStore.getState().subtitleSettings.useStyle).toBe(true)
  })
})
