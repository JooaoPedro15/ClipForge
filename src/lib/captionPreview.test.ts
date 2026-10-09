import { describe, expect, test } from 'vitest'

import { buildCaptionCards, cleanCaptionText, wrapCaptionLines } from '@/lib/captionPreview'

const plain = {
  uppercase: false,
  lowercase: false,
  noAccents: false,
  noPunctuation: false,
  maxWidth: 42,
  maxWords: 0,
}

describe('cleanCaptionText', () => {
  test('remove pontuacao sem perder acento, como o remove_punctuation do python', () => {
    expect(cleanCaptionText('Mano, é impossível!', { ...plain, noPunctuation: true })).toBe('Mano é impossível')
  })

  test('remove acentos e cedilha', () => {
    expect(cleanCaptionText('ação é impossível', { ...plain, noAccents: true })).toBe('acao e impossivel')
  })

  test('maiuscula vence minuscula quando as duas estao ligadas', () => {
    expect(cleanCaptionText('Olha só', { ...plain, uppercase: true, lowercase: true })).toBe('OLHA SÓ')
  })

  test('junta espacos que sobram depois de limpar', () => {
    expect(cleanCaptionText('Mano ,  olha', { ...plain, noPunctuation: true })).toBe('Mano olha')
  })
})

describe('wrapCaptionLines', () => {
  test('quebra por largura igual ao split_text_into_lines', () => {
    expect(wrapCaptionLines('esse chefe é impossível olha o tamanho', 16)).toEqual([
      'esse chefe é',
      'impossível olha',
      'o tamanho',
    ])
  })

  test('palavra maior que a largura fica sozinha na linha', () => {
    expect(wrapCaptionLines('inacreditavelmente bom', 5)).toEqual(['inacreditavelmente', 'bom'])
  })
})

describe('buildCaptionCards', () => {
  test('sem limite de palavras vira uma legenda so', () => {
    expect(buildCaptionCards('Mano, olha isso.', plain)).toEqual([['Mano, olha isso.']])
  })

  test('limite de palavras divide em varias legendas', () => {
    expect(buildCaptionCards('um dois tres quatro cinco', { ...plain, maxWords: 2 })).toEqual([
      ['um dois'],
      ['tres quatro'],
      ['cinco'],
    ])
  })
})
