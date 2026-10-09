// Previa da pre-edicao no Inspetor: aplica as regras do Python num trecho de exemplo
// pra mostrar o quanto cada intensidade encurta. Os numeros sao os mesmos do
// PREEDIT_MODE_SETTINGS (python/clip_splitter_service.py): segundos maximos que
// cada tipo de pausa pode manter.
import type { ClipSplitterPreEditMode } from '@/types/clipSplitter'

export type PauseType = 'dead_silence' | 'breathing_pause' | 'dramatic_pause' | 'mid_idea_pause' | 'between_ideas'

const MAX_KEEP_SEC: Record<ClipSplitterPreEditMode, Record<PauseType, number>> = {
  conservative: { dead_silence: 0.3, breathing_pause: 0.5, dramatic_pause: 0.9, mid_idea_pause: 0.6, between_ideas: 0.5 },
  balanced: { dead_silence: 0.25, breathing_pause: 0.4, dramatic_pause: 0.75, mid_idea_pause: 0.5, between_ideas: 0.35 },
  aggressive: { dead_silence: 0.15, breathing_pause: 0.3, dramatic_pause: 0.6, mid_idea_pause: 0.4, between_ideas: 0.25 },
}

export const PAUSE_LABELS: Record<PauseType, string> = {
  dead_silence: 'Silêncio morto',
  breathing_pause: 'Respiro',
  dramatic_pause: 'Pausa dramática',
  mid_idea_pause: 'Pausa no meio da ideia',
  between_ideas: 'Pausa entre ideias',
}

// Quanto da pausa sobra. No Forte, silencio morto de 4s+ sai inteiro.
export function keptPauseSeconds(type: PauseType, durationSec: number, mode: ClipSplitterPreEditMode): number {
  if (mode === 'aggressive' && type === 'dead_silence' && durationSec >= 4) {
    return 0
  }
  return Math.min(durationSec, MAX_KEEP_SEC[mode][type])
}

export interface PreviewBlock {
  kind: 'speech' | PauseType
  beforeSec: number
  afterSec: number
}

// Trecho tipico de gameplay: fala intercalada com um de cada tipo de pausa.
const SAMPLE: Array<[PreviewBlock['kind'], number]> = [
  ['speech', 2],
  ['breathing_pause', 0.6],
  ['speech', 1.5],
  ['dramatic_pause', 1.8],
  ['speech', 2.2],
  ['dead_silence', 5],
  ['speech', 1.2],
  ['mid_idea_pause', 1],
  ['speech', 1.8],
  ['between_ideas', 2.4],
  ['speech', 1.5],
]

export function simulatePreEdit(mode: ClipSplitterPreEditMode) {
  const blocks: PreviewBlock[] = SAMPLE.map(([kind, beforeSec]) => ({
    kind,
    beforeSec,
    afterSec: kind === 'speech' ? beforeSec : keptPauseSeconds(kind, beforeSec, mode),
  }))
  const sum = (key: 'beforeSec' | 'afterSec') => blocks.reduce((total, block) => total + block[key], 0)
  return { blocks, beforeSec: sum('beforeSec'), afterSec: sum('afterSec') }
}
