import crypto from 'node:crypto'
import path from 'node:path'

import { ipcMain, type WebContents } from 'electron'

import { resolveProjectRoot, resolveScriptPath } from '../python/pythonEnv.js'
import { gpuQueue, type JobResult } from '../python/gpuQueue.js'
import { runPython, type PythonRun } from '../python/pythonProcess.js'
import { decideOutcome, describeExitCode, looksLikeGpuFailure, parseRunnerLine } from '../python/runnerEvents.js'

// Tipos locais que descrevem a fila do SubtitleForge dentro do processo principal.
type SubtitleModel = 'tiny' | 'base' | 'small' | 'medium' | 'large-v3'
type SubtitleStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'

interface SubtitleTaskOptions {
  model: SubtitleModel
  language: string
  beamSize: number
  maxWidth: number
  maxWords: number
  uppercase: boolean
  lowercase: boolean
  noAccents: boolean
  noPunctuation: boolean
  useCpu: boolean
  translateTo: string[]
  videoType: string
  outputPath?: string | null
}

interface SubtitleEventPayload {
  taskId: string
  filePath: string
  fileName: string
  model: SubtitleModel
  language: string
  device: 'cpu' | 'cuda'
  status: SubtitleStatus
  stage: string
  message: string
  progress: number | null
  queuePosition?: number
  processedSegments?: number
  totalSegments?: number
  outputPath?: string | null
  startedAt?: number
  completedAt?: number
  durationSec?: number
  detectedLanguage?: string
  translatedOutputs?: Record<string, string>
  translationErrors?: Record<string, string>
}

interface SubtitleErrorPayload extends SubtitleEventPayload {
  error: string
}

interface RunnerStatusEvent {
  event: 'status'
  status: 'preparing' | 'processing'
  stage: string
  message: string
  progress?: number | null
  processedSegments?: number
  totalSegments?: number
  outputPath?: string | null
  detectedLanguage?: string
  durationSec?: number
}

interface RunnerDoneEvent {
  event: 'done'
  status: 'completed'
  stage: string
  message: string
  progress?: number | null
  processedSegments?: number
  totalSegments?: number
  outputPath?: string | null
  detectedLanguage?: string
  durationSec?: number
}

interface RunnerErrorEvent {
  event: 'error'
  status: 'error'
  stage: string
  message: string
  error: string
  progress?: number | null
  processedSegments?: number
  totalSegments?: number
  outputPath?: string | null
  detectedLanguage?: string
}

interface RunnerTranslationDoneEvent {
  event: 'translation-done'
  status: 'completed'
  stage: string
  message: string
  targetLang: string
  outputPath?: string
  error?: string
}

interface RunnerTranslationErrorEvent {
  event: 'translation-error'
  status: 'error'
  stage: string
  message: string
  targetLang: string
  outputPath?: string
  error?: string
}

type RunnerTranslationEvent = RunnerTranslationDoneEvent | RunnerTranslationErrorEvent

type RunnerEvent = RunnerStatusEvent | RunnerDoneEvent | RunnerErrorEvent | RunnerTranslationEvent

const RUNNER_EVENTS = ['status', 'done', 'error', 'translation-done', 'translation-error'] as const

interface SubtitleTaskRecord {
  id: string
  sender: WebContents
  filePath: string
  fileName: string
  options: SubtitleTaskOptions
  status: SubtitleStatus
  outputPath: string | null
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  process: PythonRun | null
  cancelRequested: boolean
  processedSegments: number
  totalSegments: number | null
  detectedLanguage: string | null
  lastMessage: string
  lastError: string | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
  hasRetriedWithCpu: boolean
  translatedOutputs: Record<string, string>
  translationErrors: Record<string, string>
}

// Tarefas desta sessao (a ordem de execucao fica na fila unica de GPU).
const tasks = new Map<string, SubtitleTaskRecord>()

const defaultOptions: SubtitleTaskOptions = {
  model: 'large-v3',
  language: 'pt',
  beamSize: 5,
  maxWidth: 42,
  maxWords: 0,
  uppercase: false,
  lowercase: false,
  noAccents: false,
  noPunctuation: false,
  useCpu: false,
  translateTo: [],
  videoType: '',
  outputPath: null,
}

// Normaliza os parametros recebidos do renderer antes de iniciar o runner Python.
function normalizeOptions(options: Partial<SubtitleTaskOptions> | undefined): SubtitleTaskOptions {
  return {
    ...defaultOptions,
    ...options,
    beamSize: Math.max(1, options?.beamSize ?? defaultOptions.beamSize),
    maxWidth: Math.max(10, options?.maxWidth ?? defaultOptions.maxWidth),
    maxWords: Math.max(0, options?.maxWords ?? defaultOptions.maxWords),
    language: (options?.language ?? defaultOptions.language).trim() || defaultOptions.language,
    translateTo: Array.from(
      new Set((options?.translateTo ?? defaultOptions.translateTo).map((lang) => lang.trim()).filter(Boolean)),
    ),
    videoType: (options?.videoType ?? defaultOptions.videoType).trim(),
    outputPath: options?.outputPath?.trim() || null,
  }
}

// Encaminha eventos para o renderer apenas se o WebContents ainda estiver vivo.
function emit(
  sender: WebContents,
  channel: 'subtitle:progress' | 'subtitle:done' | 'subtitle:error',
  payload: SubtitleEventPayload | SubtitleErrorPayload,
) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

// Construi o payload padrao usado em progresso, conclusao e erro.
function toPayload(task: SubtitleTaskRecord, overrides: Partial<SubtitleEventPayload>): SubtitleEventPayload {
  return {
    taskId: task.id,
    filePath: task.filePath,
    fileName: task.fileName,
    model: task.options.model,
    language: task.options.language,
    device: task.options.useCpu ? 'cpu' : 'cuda',
    status: task.status,
    stage: 'idle',
    message: task.lastMessage,
    progress: null,
    outputPath: task.outputPath,
    processedSegments: task.processedSegments,
    totalSegments: task.totalSegments ?? undefined,
    startedAt: task.startedAt ?? undefined,
    completedAt: task.completedAt ?? undefined,
    detectedLanguage: task.detectedLanguage ?? undefined,
    translatedOutputs: task.translatedOutputs,
    translationErrors: task.translationErrors,
    ...overrides,
  }
}

// Emissores especializados para simplificar o fluxo de notificacoes do renderer.
function emitProgress(task: SubtitleTaskRecord, overrides: Partial<SubtitleEventPayload>) {
  emit(task.sender, 'subtitle:progress', toPayload(task, overrides))
}

function emitDone(task: SubtitleTaskRecord, durationSec: number) {
  emit(task.sender, 'subtitle:done', {
    ...toPayload(task, {
      status: 'completed',
      stage: 'done',
      message: task.lastMessage || 'Transcricao concluida.',
      progress: 100,
      completedAt: task.completedAt ?? Date.now(),
      durationSec,
    }),
    status: 'completed',
    progress: 100,
    completedAt: task.completedAt ?? Date.now(),
    durationSec,
  })
}

function emitError(task: SubtitleTaskRecord, message: string, status: 'error' | 'cancelled') {
  const payload: SubtitleErrorPayload = {
    ...toPayload(task, {
      status,
      stage: status,
      message,
      progress: status === 'cancelled' ? task.processedSegments : null,
      completedAt: task.completedAt ?? Date.now(),
    }),
    status,
    error: message,
  }

  emit(task.sender, 'subtitle:error', payload)
}

// Avisa a tela da posicao da tarefa na fila unica de GPU (chamado pela fila sempre que ela anda).
function emitQueued(task: SubtitleTaskRecord, position: number, isNext: boolean) {
  task.status = 'queued'
  task.lastMessage = isNext ? 'Aguardando inicializacao...' : `Na fila (${position})`

  emitProgress(task, {
    status: 'queued',
    stage: 'queued',
    message: task.lastMessage,
    progress: null,
    queuePosition: position,
  })
}

// Resolve onde esta o projeto subtitle-forge que contem ambiente Python e dependencias.
export function resolveSubtitleForgeRoot() {
  return resolveProjectRoot(
    [process.env.CLIPFORGE_SUBTITLE_FORGE_PATH, path.resolve(process.cwd(), '../subtitle-forge'), 'D:\\Projetos\\subtitle-forge'],
    'subtitle_forge.py',
  )
}

// Localiza o script Python que sera usado como runner da transcricao, preferindo o runner local corrigido do Studio.
// Retorna o caminho encontrado e a lista de candidatos verificados para uso em mensagens de erro.
export function resolveRunnerScriptPath(forgeRoot: string): { scriptPath: string | null; checked: string[] } {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'subtitle_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'subtitle_service.py'),
    path.join(forgeRoot, 'subtitle_forge.py'),
  ])
}

// Expoe um snapshot somente-leitura de uma tarefa pra outros modulos IPC (ex.: subtitleBurn)
// sem entregar o Map mutavel interno.
export function getSubtitleTaskSnapshot(taskId: string) {
  const task = tasks.get(taskId)
  if (!task) {
    return null
  }

  return {
    filePath: task.filePath,
    outputPath: task.outputPath,
    language: task.options.language,
    detectedLanguage: task.detectedLanguage,
    videoType: task.options.videoType,
    status: task.status,
  }
}

// Traduz as opcoes da tarefa para argumentos de linha de comando do processo Python.
export function buildProcessArgs(serviceScriptPath: string, task: SubtitleTaskRecord) {
  const args = [
    serviceScriptPath,
    task.filePath,
    '--model',
    task.options.model,
    '--language',
    task.options.language,
    '--beam-size',
    String(task.options.beamSize),
    '--max-width',
    String(task.options.maxWidth),
  ]

  if (task.options.maxWords > 0) {
    args.push('--max-words', String(task.options.maxWords))
  }

  if (task.options.uppercase) {
    args.push('--uppercase')
  }

  if (task.options.lowercase) {
    args.push('--lowercase')
  }

  if (task.options.noAccents) {
    args.push('--no-accents')
  }

  if (task.options.noPunctuation) {
    args.push('--no-punctuation')
  }

  if (task.options.useCpu) {
    args.push('--cpu')
  }

  if (task.options.translateTo.length > 0) {
    args.push('--translate-to', task.options.translateTo.join(','))
  }

  // Uma linha de contexto ("gameplay de terror", "corte engraçado") — muda o
  // registro do chines no estagio 1 da traducao.
  if (task.options.videoType) {
    args.push('--video-type', task.options.videoType)
  }

  if (task.options.outputPath) {
    args.push('--output', task.options.outputPath)
  }

  return args
}

// Identifica eventos JSON emitidos pelo runner; logs livres seguem outro caminho.
export function parseRunnerEvent(line: string): RunnerEvent | null {
  return parseRunnerLine<RunnerEvent>(line, RUNNER_EVENTS)
}

// Interpreta logs em texto puro para aproveitar mensagens mesmo sem JSON estruturado.
function applyPlaintextRunnerLine(task: SubtitleTaskRecord, line: string) {
  task.lastMessage = line

  const outputMatch = line.match(/salvo em:\s*(.+)$/i)
  if (outputMatch?.[1]) {
    task.outputPath = outputMatch[1].trim()
  }

  const languageMatch = line.match(/idioma detectado:\s*([a-z-]+)/i)
  if (languageMatch?.[1]) {
    task.detectedLanguage = languageMatch[1]
  }

  const segmentsMatch = line.match(/(\d+)\s+segmentos\s+processados/i)
  if (segmentsMatch?.[1]) {
    task.processedSegments = Number(segmentsMatch[1]) || task.processedSegments
  }

  if (line.toLowerCase().includes('transcrevendo')) {
    task.status = 'processing'
  } else if (line.toLowerCase().includes('carregando modelo') || line.toLowerCase().includes('modelo carregado')) {
    task.status = 'preparing'
  }

  emitProgress(task, {
    status: task.status,
    stage: 'log',
    message: task.lastMessage,
    progress: null,
    processedSegments: task.processedSegments,
    totalSegments: task.totalSegments ?? undefined,
    outputPath: task.outputPath,
    detectedLanguage: task.detectedLanguage ?? undefined,
    queuePosition: undefined,
  })
}

// Aplica eventos estruturados do runner ao estado em memoria da tarefa.
function applyRunnerEvent(task: SubtitleTaskRecord, event: RunnerEvent) {
  task.lastMessage = event.message

  if (event.event === 'translation-done') {
    task.translatedOutputs = { ...task.translatedOutputs, [event.targetLang]: event.outputPath ?? '' }
    emitProgress(task, {
      status: task.status,
      stage: event.stage,
      message: event.message,
      progress: null,
      translatedOutputs: task.translatedOutputs,
      translationErrors: task.translationErrors,
    })
    return
  }

  if (event.event === 'translation-error') {
    task.translationErrors = { ...task.translationErrors, [event.targetLang]: event.error ?? event.message }
    emitProgress(task, {
      status: task.status,
      stage: event.stage,
      message: event.message,
      progress: null,
      translatedOutputs: task.translatedOutputs,
      translationErrors: task.translationErrors,
    })
    return
  }

  if (typeof event.processedSegments === 'number') {
    task.processedSegments = event.processedSegments
  }

  if (typeof event.totalSegments === 'number') {
    task.totalSegments = event.totalSegments
  }

  if (typeof event.outputPath === 'string') {
    task.outputPath = event.outputPath
  }

  if (typeof event.detectedLanguage === 'string') {
    task.detectedLanguage = event.detectedLanguage
  }

  if (event.event === 'status') {
    task.status = event.status
    emitProgress(task, {
      status: event.status,
      stage: event.stage,
      message: event.message,
      progress: event.progress ?? null,
      processedSegments: task.processedSegments,
      totalSegments: task.totalSegments ?? undefined,
      outputPath: task.outputPath,
      detectedLanguage: task.detectedLanguage ?? undefined,
      queuePosition: undefined,
    })
    return
  }

  task.terminalEvent = event
}

// Decide o estado final da tarefa quando o processo fecha.
function finishTask(task: SubtitleTaskRecord, code: number | null) {
  task.completedAt = Date.now()
  const fallbackDurationSec = task.startedAt ? Number(((task.completedAt - task.startedAt) / 1000).toFixed(1)) : 0
  const outcome = decideOutcome({
    cancelRequested: task.cancelRequested,
    terminalEvent: task.terminalEvent,
    code,
    lastError: task.lastError,
    lastMessage: task.lastMessage,
    defaultDoneMessage: 'Transcricao concluida.',
    describeExit: (exitCode) => describeExitCode(exitCode, 'SubtitleForge'),
  })

  task.lastMessage = outcome.message
  if (outcome.kind === 'done') {
    task.status = 'completed'
    emitDone(task, outcome.durationSec ?? fallbackDurationSec)
    return
  }

  if (outcome.kind === 'cancelled') {
    task.status = 'cancelled'
    emitError(task, outcome.message, 'cancelled')
    return
  }

  task.status = 'error'
  task.lastError = outcome.error
  emitError(task, outcome.error, 'error')
}

// Detecta erros tipicos de GPU/CUDA para decidir se vale reexecutar em CPU.
function shouldRetryOnCpu(task: SubtitleTaskRecord, code: number | null) {
  if (task.options.useCpu || task.hasRetriedWithCpu) {
    return false
  }

  return looksLikeGpuFailure(`${task.lastError ?? ''}\n${task.lastMessage}`, code)
}

// Roda uma tarefa da fila de GPU: sobe o Python, acompanha e decide entre retry em CPU e desfecho.
async function runTask(task: SubtitleTaskRecord): Promise<JobResult> {
  const forgeRoot = resolveSubtitleForgeRoot()
  if (!forgeRoot) {
    task.status = 'error'
    task.completedAt = Date.now()
    task.lastMessage = 'Projeto subtitle-forge nao encontrado.'
    emitError(
      task,
      'Projeto subtitle-forge nao encontrado. Configure em D:\\Projetos\\subtitle-forge ou use CLIPFORGE_SUBTITLE_FORGE_PATH.',
      'error',
    )
    return 'done'
  }

  const { scriptPath: runnerScriptPath, checked: runnerCheckedPaths } = resolveRunnerScriptPath(forgeRoot)
  if (!runnerScriptPath) {
    task.status = 'error'
    task.completedAt = Date.now()
    task.lastMessage = 'Script de transcricao nao encontrado.'
    emitError(
      task,
      `Script Python nao encontrado. Caminhos verificados:\n${runnerCheckedPaths.join('\n')}`,
      'error',
    )
    return 'done'
  }

  task.status = 'preparing'
  task.startedAt = Date.now()
  task.lastMessage = 'Inicializando SubtitleForge...'

  emitProgress(task, {
    status: 'preparing',
    stage: 'starting',
    message: task.lastMessage,
    progress: 5,
    queuePosition: undefined,
  })

  const run = runPython({
    root: forgeRoot,
    scriptArgs: buildProcessArgs(runnerScriptPath, task),
    logTag: 'subtitle-service',
    onStdoutLine: (line) => {
      const event = parseRunnerEvent(line)
      if (event) {
        applyRunnerEvent(task, event)
      } else {
        applyPlaintextRunnerLine(task, line)
      }
    },
    onStderrLine: (line) => {
      task.lastError = line
    },
  })
  task.process = run

  const { code, spawnError, lastStderrLine } = await run.done
  task.process = null
  if (spawnError && !lastStderrLine) {
    task.lastError = spawnError
  }

  if (shouldRetryOnCpu(task, code)) {
    // Volta pro topo da fila em CPU quando o ambiente GPU falha, antes de desistir.
    task.terminalEvent = null
    task.lastError = null
    task.options = {
      ...task.options,
      useCpu: true,
    }
    task.hasRetriedWithCpu = true
    task.status = 'queued'
    task.lastMessage = 'CUDA indisponivel. Tentando novamente em CPU...'
    emitProgress(task, {
      status: 'queued',
      stage: 'retrying-cpu',
      message: task.lastMessage,
      progress: null,
      queuePosition: 1,
    })
    return 'requeue-front'
  }

  finishTask(task, code)
  return 'done'
}

export function registerSubtitleHandlers() {
  // Cria novas tasks, coloca na fila e devolve o taskId ao renderer.
  ipcMain.handle('subtitle:process', async (event, filePath: string, options?: Partial<SubtitleTaskOptions>) => {
    const resolvedOptions = normalizeOptions(options)
    const taskId = crypto.randomUUID()
    const fileName = path.basename(filePath)

    const task: SubtitleTaskRecord = {
      id: taskId,
      sender: event.sender,
      filePath,
      fileName,
      options: resolvedOptions,
      status: 'queued',
      outputPath: resolvedOptions.outputPath ?? null,
      createdAt: Date.now(),
      startedAt: null,
      completedAt: null,
      process: null,
      cancelRequested: false,
      processedSegments: 0,
      totalSegments: null,
      detectedLanguage: null,
      lastMessage: 'Tarefa adicionada a fila.',
      lastError: null,
      terminalEvent: null,
      hasRetriedWithCpu: false,
      translatedOutputs: {},
      translationErrors: {},
    }

    tasks.set(taskId, task)
    emitQueued(task, gpuQueue.size + 1, gpuQueue.size === 0 && !gpuQueue.busy)
    gpuQueue.enqueue({
      id: taskId,
      onQueued: (position, isNext) => emitQueued(task, position, isNext),
      run: () => runTask(task),
    })

    return taskId
  })

  // Cancela tanto tarefas ativas quanto itens que ainda estavam aguardando na fila.
  ipcMain.handle('subtitle:cancel', async (_event, taskId: string) => {
    const task = tasks.get(taskId)
    if (!task) {
      return false
    }

    if (task.process) {
      task.cancelRequested = true
      task.status = 'cancelled'
      task.lastMessage = 'Cancelando transcricao...'
      emitProgress(task, {
        status: 'cancelled',
        stage: 'cancelling',
        message: task.lastMessage,
        progress: null,
        queuePosition: undefined,
      })
      task.process.kill()
      return true
    }

    if (gpuQueue.has(taskId)) {
      task.status = 'cancelled'
      task.completedAt = Date.now()
      task.lastMessage = 'Tarefa removida da fila.'
      emitError(task, task.lastMessage, 'cancelled')
      gpuQueue.remove(taskId)
      return true
    }

    return false
  })
}
