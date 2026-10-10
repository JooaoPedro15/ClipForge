import { describe, expect, test } from 'vitest'

import { pickPreferences, restorePreferences } from '@/store/preferences'

const defaults = {
  activeTool: 'subtitle-forge' as const,
  subtitleSettings: { model: 'large-v3', format: 'long', uppercase: false, translateTo: [] as string[], outputPath: null as string | null },
  clipSplitterSettings: { preEditMode: 'balanced', silenceMinDurationSec: 0.45, outputDir: null as string | null },
  cortesSettings: { templatePath: '', minSec: 70, titlesWithAi: true },
}

describe('pickPreferences', () => {
  test('guarda ferramenta e opcoes, mas nao os caminhos de saida', () => {
    const picked = pickPreferences({
      ...defaults,
      subtitleSettings: { ...defaults.subtitleSettings, format: 'shorts', outputPath: 'D:\\ep01.srt' },
      clipSplitterSettings: { ...defaults.clipSplitterSettings, outputDir: 'D:\\saida' },
    })
    expect(picked.subtitleSettings).toEqual({ model: 'large-v3', format: 'shorts', uppercase: false, translateTo: [] })
    expect(picked.clipSplitterSettings).toEqual({ preEditMode: 'balanced', silenceMinDurationSec: 0.45 })
    expect(picked.activeTool).toBe('subtitle-forge')
  })

  test('lembra o molde dos cortes: vale pra todo react', () => {
    const picked = pickPreferences({ ...defaults, cortesSettings: { ...defaults.cortesSettings, templatePath: 'D:\\molde.xml' } })
    expect(picked.cortesSettings).toEqual({ templatePath: 'D:\\molde.xml', minSec: 70, titlesWithAi: true })
  })
})

describe('restorePreferences', () => {
  test('aplica o que foi salvo por cima do padrao', () => {
    const restored = restorePreferences(
      { activeTool: 'clip-splitter', subtitleSettings: { format: 'shorts', uppercase: true }, clipSplitterSettings: { preEditMode: 'aggressive' } },
      defaults,
    )
    expect(restored.activeTool).toBe('clip-splitter')
    expect(restored.subtitleSettings).toEqual({ ...defaults.subtitleSettings, format: 'shorts', uppercase: true })
    expect(restored.clipSplitterSettings.preEditMode).toBe('aggressive')
  })

  test('abre direto nos cortes e mescla as opcoes deles', () => {
    const restored = restorePreferences({ activeTool: 'cortes', cortesSettings: { minSec: 60, titlesWithAi: 'sim' } }, defaults)
    expect(restored.activeTool).toBe('cortes')
    expect(restored.cortesSettings).toEqual({ templatePath: '', minSec: 60, titlesWithAi: true })
  })

  test('opcao nova que nao existia quando salvou fica com o padrao', () => {
    const restored = restorePreferences({ subtitleSettings: { format: 'shorts' } }, defaults)
    expect(restored.subtitleSettings.model).toBe('large-v3')
  })

  test('ignora tipo errado, chave desconhecida e ferramenta que nao existe', () => {
    const restored = restorePreferences(
      { activeTool: 'partner-scout', subtitleSettings: { uppercase: 'sim', translateTo: 'zh', invented: 1 } },
      defaults,
    )
    expect(restored.activeTool).toBe('subtitle-forge')
    expect(restored.subtitleSettings).toEqual(defaults.subtitleSettings)
  })

  test('dado corrompido devolve o padrao', () => {
    expect(restorePreferences(null, defaults)).toEqual(defaults)
    expect(restorePreferences('lixo', defaults)).toEqual(defaults)
  })
})
