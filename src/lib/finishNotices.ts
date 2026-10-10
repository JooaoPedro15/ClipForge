// Texto do aviso do sistema quando uma tarefa termina. Cancelamento e progresso nao
// avisam: so o que o usuario precisa saber estando em outra janela.
import { formatDuration } from '@/lib/utils'
import type { ClipSplitterDoneEvent, ClipSplitterErrorEvent } from '@/types/clipSplitter'
import type { CortesDoneEvent, CortesErrorEvent } from '@/types/cortes'
import type { HardsubEvent, HardsubMode, SubtitleDoneEvent, SubtitleErrorEvent } from '@/types/subtitle'

export interface Notice {
  title: string
  body: string
}

const BURN_LABELS: Record<HardsubMode, string> = {
  zh: 'só chinês',
  'zh-en': 'chinês + inglês',
  'zh-original': 'chinês + idioma original',
  'translate-zh': 'tradução nova',
}

// Traceback do Python nao cabe num aviso: fica a primeira linha, curta.
function firstLine(text: string | null | undefined): string {
  const line = ((text ?? '').split('\n')[0] ?? '').trim()
  return line.length > 140 ? `${line.slice(0, 137)}...` : line
}

export function subtitleNotice(event: SubtitleDoneEvent | SubtitleErrorEvent): Notice | null {
  if (event.status === 'completed') {
    return { title: 'Legenda pronta', body: `${event.fileName} em ${formatDuration(event.durationSec)}.` }
  }
  if (event.status === 'error') {
    return { title: 'A legenda parou com erro', body: `${event.fileName}: ${firstLine(event.error)}` }
  }
  return null
}

export function burnNotice(event: HardsubEvent, fileName: string): Notice | null {
  if (event.status === 'completed') {
    return event.mode === 'translate-zh'
      ? { title: 'Tradução nova pronta', body: `${fileName}: confira o .zh.srt antes de queimar.` }
      : { title: 'Vídeo com legenda pronto', body: `${fileName}: ${BURN_LABELS[event.mode]}.` }
  }
  if (event.status === 'error') {
    return { title: 'A queima parou com erro', body: `${fileName}: ${firstLine(event.error)}` }
  }
  return null
}

export function preEditNotice(event: ClipSplitterDoneEvent | ClipSplitterErrorEvent): Notice | null {
  if (event.status === 'completed') {
    const clip = event.clips?.[0]
    const shrink =
      clip && event.sourceDurationSec
        ? ` ${formatDuration(event.sourceDurationSec)} viraram ${formatDuration(clip.durationSec)}.`
        : ''
    return { title: 'Pré-edição pronta', body: `${event.sourceName}:${shrink || ' pronta pra revisar.'}` }
  }
  if (event.status === 'error') {
    return { title: 'A pré-edição parou com erro', body: `${event.sourceName}: ${firstLine(event.error)}` }
  }
  return null
}

export function cortesNotice(event: CortesDoneEvent | CortesErrorEvent): Notice | null {
  if (event.status === 'completed') {
    const count = event.analysis.clips.length
    return {
      title: event.kind === 'resegment' ? 'Clipes refeitos' : 'Cortes prontos',
      body: `${event.sourceName}: ${count} ${count === 1 ? 'clipe' : 'clipes'}.`,
    }
  }
  if (event.status === 'error') {
    return { title: 'Os cortes pararam com erro', body: `${event.sourceName}: ${firstLine(event.error)}` }
  }
  return null
}
