import { describe, expect, test } from 'vitest'

import { useAppStore } from '@/store/appStore'
import { PREFERENCES_KEY } from '@/store/preferences'

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

describe('preferencias lembradas', () => {
  test('grava as opcoes do Inspetor, mas nao o caminho de saida', () => {
    useAppStore.getState().patchSubtitleSettings({ format: 'shorts' })
    useAppStore.getState().setSubtitleOutputPath('D:\\ep01.srt')

    const saved = useAppStore.persist.getOptions().storage?.getItem(PREFERENCES_KEY) as {
      state: { subtitleSettings: Record<string, unknown> }
    }
    expect(saved.state.subtitleSettings.format).toBe('shorts')
    expect(saved.state.subtitleSettings).not.toHaveProperty('outputPath')
  })
})

describe('cortes', () => {
  test('o molde escolhido fica salvo junto com as opcoes do Inspetor', () => {
    useAppStore.getState().patchCortesSettings({ templatePath: 'D:\\molde.xml', minSec: 60 })

    const saved = useAppStore.persist.getOptions().storage?.getItem(PREFERENCES_KEY) as {
      state: { cortesSettings: Record<string, unknown> }
    }
    expect(saved.state.cortesSettings).toMatchObject({ templatePath: 'D:\\molde.xml', minSec: 60, titlesWithAi: true })
  })
})
