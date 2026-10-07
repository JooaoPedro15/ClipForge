import { describe, expect, it } from 'vitest'

import { decideOutcome, describeExitCode, looksLikeGpuFailure, parseRunnerLine } from './runnerEvents'

describe('parseRunnerLine', () => {
  const allowed = ['status', 'done', 'error'] as const

  it('aceita so JSON de um evento permitido com status, stage e message', () => {
    expect(parseRunnerLine('{"event":"status","status":"processing","stage":"x","message":"m","progress":3}', allowed)).toEqual({
      event: 'status',
      status: 'processing',
      stage: 'x',
      message: 'm',
      progress: 3,
    })
    expect(parseRunnerLine('{"event":"outro","status":"s","stage":"x","message":"m"}', allowed)).toBeNull()
    expect(parseRunnerLine('{"event":"done","stage":"x","message":"m"}', allowed)).toBeNull()
    expect(parseRunnerLine('Idioma detectado: pt', allowed)).toBeNull()
    expect(parseRunnerLine('null', allowed)).toBeNull()
  })
})

describe('decideOutcome', () => {
  const base = {
    cancelRequested: false,
    terminalEvent: null,
    code: 1,
    lastError: null,
    lastMessage: 'ultima mensagem',
    defaultDoneMessage: 'Concluido.',
    describeExit: (code: number | null) => `codigo ${code}`,
  }

  it('cancelamento vence tudo', () => {
    expect(decideOutcome({ ...base, cancelRequested: true, terminalEvent: { event: 'done', message: 'ok' } })).toEqual({
      kind: 'cancelled',
      message: 'Processo cancelado pelo usuario.',
    })
  })

  it('evento done do runner vence o codigo de saida', () => {
    expect(decideOutcome({ ...base, terminalEvent: { event: 'done', message: 'Pronto.', durationSec: 2 } })).toEqual({
      kind: 'done',
      message: 'Pronto.',
      durationSec: 2,
    })
  })

  it('evento error do runner usa o detalhe do erro (ou a mensagem se faltar)', () => {
    expect(decideOutcome({ ...base, code: 0, terminalEvent: { event: 'error', message: 'Falhou.', error: 'detalhe' } })).toEqual({
      kind: 'error',
      message: 'Falhou.',
      error: 'detalhe',
    })
    expect(decideOutcome({ ...base, terminalEvent: { event: 'error', message: 'Falhou.' } })).toEqual({
      kind: 'error',
      message: 'Falhou.',
      error: 'Falhou.',
    })
  })

  it('sem evento: codigo 0 e sucesso, a menos que o evento done seja obrigatorio', () => {
    expect(decideOutcome({ ...base, code: 0 })).toEqual({ kind: 'done', message: 'ultima mensagem', durationSec: null })
    expect(decideOutcome({ ...base, code: 0, lastMessage: '' })).toEqual({ kind: 'done', message: 'Concluido.', durationSec: null })
    expect(decideOutcome({ ...base, code: 0, requireDoneEvent: true })).toEqual({ kind: 'error', message: 'codigo 0', error: 'codigo 0' })
  })

  it('sem evento e codigo != 0: ultimo stderr ou descricao do codigo', () => {
    expect(decideOutcome({ ...base, lastError: 'Traceback...' })).toEqual({ kind: 'error', message: 'Traceback...', error: 'Traceback...' })
    expect(decideOutcome(base)).toEqual({ kind: 'error', message: 'codigo 1', error: 'codigo 1' })
  })
})

describe('looksLikeGpuFailure', () => {
  it('reconhece crash nativo e mensagens de CUDA/CTranslate2', () => {
    expect(looksLikeGpuFailure('', 3221226505)).toBe(true)
    expect(looksLikeGpuFailure('', 3221225477)).toBe(true)
    expect(looksLikeGpuFailure('Could not load library cublas64_12.dll', 1)).toBe(true)
    expect(looksLikeGpuFailure('RuntimeError: CUDA out of memory', 1)).toBe(true)
    expect(looksLikeGpuFailure('ctranslate2 error', 1)).toBe(true)
    expect(looksLikeGpuFailure('Failed to load library', 1)).toBe(true)
    expect(looksLikeGpuFailure('arquivo corrompido', 1)).toBe(false)
  })
})

describe('describeExitCode', () => {
  it('explica os crashes nativos do Windows com o nome da ferramenta', () => {
    expect(describeExitCode(3221226505, 'Pre-Editor')).toBe(
      'O Pre-Editor encerrou com erro nativo do Windows (3221226505 / 0xC0000409). Isso costuma indicar falha em CUDA, CTranslate2 ou driver de GPU.',
    )
    expect(describeExitCode(3221225477, 'Pre-Editor')).toBe(
      'O Pre-Editor encerrou com violacao de acesso do Windows (3221225477 / 0xC0000005). Isso costuma indicar falha em biblioteca nativa, driver ou memoria da GPU.',
    )
    expect(describeExitCode(2, 'Pre-Editor')).toBe('Processo finalizado com codigo 2.')
    expect(describeExitCode(null, 'Pre-Editor')).toBe('Processo finalizado com codigo desconhecido.')
  })
})
