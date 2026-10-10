// O que o app lembra entre uma abertura e outra: a ferramenta aberta e as opcoes do
// Inspetor. Caminhos de saida ficam de fora: valem pra um video so, e reaproveitar um
// .srt fixo sobrescreveria o arquivo do video anterior.
import type { StateStorage } from 'zustand/middleware'

import type { ToolId } from '@/types/subtitle'

export const PREFERENCES_KEY = 'clipforge:preferencias'

const TOOL_IDS: ToolId[] = ['subtitle-forge', 'clip-splitter', 'cortes']

type Settings = object

interface PreferenceState<S extends Settings, C extends Settings, K extends Settings> {
  activeTool: ToolId
  subtitleSettings: S
  clipSplitterSettings: C
  // O molde dos Cortes entra junto: vale pra todo react, nao e saida de um video so.
  cortesSettings: K
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function without<T extends Settings, K extends string>(source: T, key: K): Omit<T, K> {
  return Object.fromEntries(Object.entries(source).filter(([name]) => name !== key)) as Omit<T, K>
}

export function pickPreferences<S extends Settings, C extends Settings, K extends Settings>(state: PreferenceState<S, C, K>) {
  return {
    activeTool: state.activeTool,
    subtitleSettings: without(state.subtitleSettings, 'outputPath'),
    clipSplitterSettings: without(state.clipSplitterSettings, 'outputDir'),
    cortesSettings: state.cortesSettings,
  }
}

// Mesmo "formato" de valor: evita que um dado corrompido troque booleano por texto.
function sameKind(value: unknown, reference: unknown): boolean {
  if (Array.isArray(reference)) {
    return Array.isArray(value) && value.every((item) => typeof item === 'string')
  }
  return typeof value === typeof reference && !Array.isArray(value)
}

// Parte do padrao e so aceita do salvo as chaves que o padrao conhece, com o mesmo tipo.
// Assim uma opcao nova (que nao existia quando salvou) nasce com o valor padrao.
function mergeKnown<T extends Settings>(base: T, saved: unknown): T {
  if (!isRecord(saved)) {
    return base
  }
  const result = { ...base } as Record<string, unknown>
  for (const [key, reference] of Object.entries(base)) {
    if (key in saved && sameKind(saved[key], reference)) {
      result[key] = saved[key]
    }
  }
  return result as T
}

export function restorePreferences<S extends Settings, C extends Settings, K extends Settings, D extends PreferenceState<S, C, K>>(
  saved: unknown,
  defaults: D,
): D {
  if (!isRecord(saved)) {
    return defaults
  }
  const tool = saved.activeTool
  return {
    ...defaults,
    activeTool: TOOL_IDS.includes(tool as ToolId) ? (tool as ToolId) : defaults.activeTool,
    subtitleSettings: mergeKnown(defaults.subtitleSettings, saved.subtitleSettings),
    clipSplitterSettings: mergeKnown(defaults.clipSplitterSettings, saved.clipSplitterSettings),
    cortesSettings: mergeKnown(defaults.cortesSettings, saved.cortesSettings),
  }
}

// localStorage do renderer (o Electron guarda em disco, por app). Nos testes (Node, sem
// window) e no modo demo fica em memoria: a demo nao pode trocar as preferencias de verdade.
export function createPreferenceStorage(): StateStorage {
  const isBrowser = typeof window !== 'undefined'
  if (isBrowser && !new URLSearchParams(window.location.search).has('demo')) {
    return window.localStorage
  }
  const memory = new Map<string, string>()
  return {
    getItem: (key) => memory.get(key) ?? null,
    setItem: (key, value) => void memory.set(key, value),
    removeItem: (key) => void memory.delete(key),
  }
}
