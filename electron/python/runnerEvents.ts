// Leitura dos eventos JSON dos servicos Python e decisao de como um job terminou.

export interface RunnerEventBase {
  event: string
  status: string
  stage: string
  message: string
}

// So devolve a linha como evento se for JSON de um tipo esperado com status/stage/message.
export function parseRunnerLine<T extends RunnerEventBase>(line: string, allowedEvents: readonly string[]): T | null {
  try {
    const parsed = JSON.parse(line) as Partial<RunnerEventBase> | null
    if (
      parsed &&
      typeof parsed.event === 'string' &&
      allowedEvents.includes(parsed.event) &&
      typeof parsed.status === 'string' &&
      typeof parsed.stage === 'string' &&
      typeof parsed.message === 'string'
    ) {
      return parsed as T
    }
  } catch {
    return null
  }

  return null
}

export type RunnerTerminalEvent =
  | { event: 'done'; message: string; durationSec?: number }
  | { event: 'error'; message: string; error?: string }

export type JobOutcome =
  | { kind: 'cancelled'; message: string }
  | { kind: 'done'; message: string; durationSec: number | null }
  | { kind: 'error'; message: string; error: string }

interface OutcomeInput {
  cancelRequested: boolean
  terminalEvent: RunnerTerminalEvent | null
  code: number | null
  lastError: string | null
  lastMessage: string
  defaultDoneMessage: string
  describeExit: (code: number | null) => string
  // Sem evento 'done', codigo 0 conta como erro (a queima precisa do caminho do arquivo gerado).
  requireDoneEvent?: boolean
}

// Prioridade: cancelado > evento done > evento error > codigo 0 > erro (ultimo stderr ou codigo).
export function decideOutcome(input: OutcomeInput): JobOutcome {
  if (input.cancelRequested) {
    return { kind: 'cancelled', message: 'Processo cancelado pelo usuario.' }
  }

  if (input.terminalEvent?.event === 'done') {
    return { kind: 'done', message: input.terminalEvent.message, durationSec: input.terminalEvent.durationSec ?? null }
  }

  if (input.terminalEvent?.event === 'error') {
    return {
      kind: 'error',
      message: input.terminalEvent.message,
      error: input.terminalEvent.error ?? input.terminalEvent.message,
    }
  }

  if (input.code === 0 && !input.requireDoneEvent) {
    return { kind: 'done', message: input.lastMessage || input.defaultDoneMessage, durationSec: null }
  }

  const message = input.lastError ?? input.describeExit(input.code)
  return { kind: 'error', message, error: message }
}

// Codigos de saida do Windows quando uma biblioteca nativa (CUDA, CTranslate2) derruba o processo.
const NATIVE_CRASH_CODE = 3221226505 // 0xC0000409
const ACCESS_VIOLATION_CODE = 3221225477 // 0xC0000005

const GPU_ERROR_MARKERS = ['cublas64_12.dll', 'cudnn', 'cuda', 'ctranslate2', 'device not found', 'failed to load library']

// Erro com cara de GPU/CUDA: vale tentar de novo em CPU antes de desistir.
export function looksLikeGpuFailure(errorText: string, code: number | null): boolean {
  if (code === NATIVE_CRASH_CODE || code === ACCESS_VIOLATION_CODE) {
    return true
  }

  const text = errorText.toLowerCase()
  return GPU_ERROR_MARKERS.some((marker) => text.includes(marker))
}

export function describeExitCode(code: number | null, toolLabel: string): string {
  if (code === NATIVE_CRASH_CODE) {
    return `O ${toolLabel} encerrou com erro nativo do Windows (3221226505 / 0xC0000409). Isso costuma indicar falha em CUDA, CTranslate2 ou driver de GPU.`
  }

  if (code === ACCESS_VIOLATION_CODE) {
    return `O ${toolLabel} encerrou com violacao de acesso do Windows (3221225477 / 0xC0000005). Isso costuma indicar falha em biblioteca nativa, driver ou memoria da GPU.`
  }

  return `Processo finalizado com codigo ${code ?? 'desconhecido'}.`
}
