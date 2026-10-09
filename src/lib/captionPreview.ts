// Previa da legenda no Inspetor. Espelha o render_srt do Python (srt_utils.py +
// text_utils.py) pra o que aparece no monitor ser o que sai no .srt.
import type { SubtitleTaskOptions } from '@/types/subtitle'

export type CaptionOptions = Pick<
  SubtitleTaskOptions,
  'uppercase' | 'lowercase' | 'noAccents' | 'noPunctuation' | 'maxWidth' | 'maxWords'
>

// Frase de exemplo com acento, virgula e exclamacao pra toda opcao ter efeito visivel.
export const SAMPLE_CAPTION = 'Mano, esse chefe é impossível! Olha o tamanho dele.'

// Mesma ordem do python: tira pontuacao, depois acento, junta espacos, aplica caixa.
// [^\p{L}\p{N}_\s] equivale ao [^\w\s] do re do python (que ja e unicode).
export function cleanCaptionText(text: string, options: CaptionOptions): string {
  let result = text
  if (options.noPunctuation) {
    result = result.replace(/[^\p{L}\p{N}_\s]/gu, '')
  }
  if (options.noAccents) {
    result = result.normalize('NFKD').replace(/\p{M}/gu, '')
  }
  result = result.replace(/\s+/g, ' ').trim()
  if (options.uppercase) {
    return result.toUpperCase()
  }
  return options.lowercase ? result.toLowerCase() : result
}

// Quebra gulosa por largura, igual ao split_text_into_lines.
export function wrapCaptionLines(text: string, maxWidth: number): string[] {
  const lines: string[] = []
  let current = ''
  for (const word of text.split(' ').filter(Boolean)) {
    if (current && current.length + 1 + word.length > maxWidth) {
      lines.push(current)
      current = word
    } else {
      current = current ? `${current} ${word}` : word
    }
  }
  if (current) {
    lines.push(current)
  }
  return lines
}

// Cada legenda (card) com suas linhas. A segmentacao real e mais esperta (respeita
// pausas e palavras fracas); aqui o corte por contagem basta pra mostrar o efeito.
export function buildCaptionCards(text: string, options: CaptionOptions): string[][] {
  const words = cleanCaptionText(text, options).split(' ').filter(Boolean)
  const size = options.maxWords > 0 ? options.maxWords : words.length
  const cards: string[][] = []
  for (let index = 0; index < words.length; index += size) {
    cards.push(wrapCaptionLines(words.slice(index, index + size).join(' '), options.maxWidth))
  }
  return cards
}
