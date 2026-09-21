import { spawn, type ChildProcessByStdio } from 'node:child_process'
import crypto from 'node:crypto'
import { existsSync } from 'node:fs'
import path from 'node:path'
import type { Readable } from 'node:stream'

import { ipcMain, type WebContents } from 'electron'

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
  child: ChildProcessByStdio<null, Readable, Readable> | null
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

// Estruturas em memoria que controlam a fila sequencial e a tarefa ativa.
const tasks = new Map<string, SubtitleTaskRecord>()
const queue: string[] = []

let activeTaskId: string | null = null

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

function refreshQueuedTasks() {
  // Recalcula a posicao de cada item da fila sempre que algo entra, sai ou conclui.
  queue.forEach((taskId, index) => {
    const task = tasks.get(taskId)
    if (!task) {
      return
    }

    task.status = 'queued'
    task.lastMessage = index === 0 && !activeTaskId ? 'Aguardando inicializacao...' : `Na fila (${index + 1})`

    emitProgress(task, {
      status: 'queued',
      stage: 'queued',
      message: task.lastMessage,
      progress: null,
      queuePosition: index + 1,
    })
  })
}

// Resolve onde esta o projeto subtitle-forge que contem ambiente Python e dependencias.
export function resolveSubtitleForgeRoot() {
  const candidates = [
    process.env.CLIPFORGE_SUBTITLE_FORGE_PATH,
    path.resolve(process.cwd(), '../subtitle-forge'),
    'D:\\Projetos\\subtitle-forge',
  ].filter((value): value is string => Boolean(value))

  return (
    candidates.find((candidate) => {
      return (
        existsSync(path.join(candidate, '.venv', 'Scripts', 'python.exe')) ||
        existsSync(path.join(candidate, 'venv', 'Scripts', 'python.exe')) ||
        existsSync(path.join(candidate, 'subtitle_forge.py'))
      )
    }) ?? null
  )
}

// Prefere o Python do venv local, mas ainda permite fallback para python do sistema.
export function resolvePythonCommand(root: string) {
  const localCandidates = [
    path.join(root, '.venv', 'Scripts', 'python.exe'),
    path.join(root, 'venv', 'Scripts', 'python.exe'),
  ]

  for (const candidate of localCandidates) {
    if (existsSync(candidate)) {
      return { command: candidate, args: [] as string[] }
    }
  }

  return { command: 'python', args: [] as string[] }
}

// Coleta caminhos de DLLs NVIDIA quando a execucao usa CUDA em ambiente virtual local.
export function resolveNvidiaBinPaths(root: string) {
  const candidates = [
    path.join(root, '.venv', 'Lib', 'site-packages', 'nvidia', 'cublas', 'bin'),
    path.join(root, '.venv', 'Lib', 'site-packages', 'nvidia', 'cudnn', 'bin'),
    path.join(root, '.venv', 'Lib', 'site-packages', 'nvidia', 'cuda_runtime', 'bin'),
    path.join(root, '.venv', 'Lib', 'site-packages', 'nvidia', 'cuda_nvrtc', 'bin'),
    path.join(root, 'venv', 'Lib', 'site-packages', 'nvidia', 'cublas', 'bin'),
    path.join(root, 'venv', 'Lib', 'site-packages', 'nvidia', 'cudnn', 'bin'),
    path.join(root, 'venv', 'Lib', 'site-packages', 'nvidia', 'cuda_runtime', 'bin'),
    path.join(root, 'venv', 'Lib', 'site-packages', 'nvidia', 'cuda_nvrtc', 'bin'),
  ]

  return candidates.filter((candidate) => existsSync(candidate))
}

// Localiza o script Python que sera usado como runner da transcricao, preferindo o runner local corrigido do Studio.
// Retorna o caminho encontrado e a lista de candidatos verificados para uso em mensagens de erro.
export function resolveRunnerScriptPath(forgeRoot: string): { scriptPath: string | null; checked: string[] } {
  const candidates = [
    path.resolve(process.cwd(), 'python', 'subtitle_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'subtitle_service.py'),
    path.join(forgeRoot, 'subtitle_forge.py'),
  ]

  const scriptPath = candidates.find((candidate) => existsSync(candidate)) ?? null

  return { scriptPath, checked: candidates }
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

// Consome stdout/stderr em blocos e libera apenas linhas completas para o parser.
function flushBuffer(buffer: string, onLine: (line: string) => void) {
  const lines = buffer.split(/\r?\n/)
  const remainder = lines.pop() ?? ''

  for (const line of lines) {
    const trimmed = line.trim()
    if (trimmed) {
      onLine(trimmed)
    }
  }

  return remainder
}

// Identifica eventos JSON emitidos pelo runner; logs livres seguem outro caminho.
export function parseRunnerEvent(line: string): RunnerEvent | null {
  try {
    const parsed = JSON.parse(line) as Partial<RunnerEvent>

    if (
      parsed &&
      (parsed.event === 'status' ||
        parsed.event === 'done' ||
        parsed.event === 'error' ||
        parsed.event === 'translation-done' ||
        parsed.event === 'translation-error') &&
      typeof parsed.status === 'string' &&
      typeof parsed.stage === 'string' &&
      typeof parsed.message === 'string'
    ) {
      return parsed as RunnerEvent
    }
  } catch {
    return null
  }

  return null
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

  if (task.cancelRequested) {
    task.status = 'cancelled'
    task.lastMessage = 'Processo cancelado pelo usuario.'
    emitError(task, task.lastMessage, 'cancelled')
    return
  }

  if (task.terminalEvent?.event === 'done') {
    task.status = 'completed'
    task.lastMessage = task.terminalEvent.message
    emitDone(task, task.terminalEvent.durationSec ?? fallbackDurationSec)
    return
  }

  if (task.terminalEvent?.event === 'error') {
    task.status = 'error'
    task.lastMessage = task.terminalEvent.message
    task.lastError = task.terminalEvent.error
    emitError(task, task.lastError ?? task.lastMessage, 'error')
    return
  }

  if (code === 0) {
    task.status = 'completed'
    task.lastMessage = task.lastMessage || 'Transcricao concluida.'
    emitDone(task, fallbackDurationSec)
    return
  }

  task.status = 'error'
  task.lastMessage = task.lastError ?? `Processo finalizado com codigo ${code ?? 'desconhecido'}.`
  emitError(task, task.lastMessage, 'error')
}

// Detecta erros tipicos de GPU/CUDA para decidir se vale reexecutar em CPU.
function shouldRetryOnCpu(task: SubtitleTaskRecord) {
  if (task.options.useCpu || task.hasRetriedWithCpu) {
    return false
  }

  const errorText = `${task.lastError ?? ''}\n${task.lastMessage}`.toLowerCase()

  return (
    errorText.includes('cublas64_12.dll') ||
    errorText.includes('cudnn') ||
    errorText.includes('cuda') ||
    errorText.includes('device not found') ||
    errorText.includes('failed to load library')
  )
}

// Motor da fila: pega o proximo item, inicia o processo Python e encadeia o restante.
async function runNextTask() {
  if (activeTaskId || queue.length === 0) {
    return
  }

  const nextTaskId = queue.shift()
  if (!nextTaskId) {
    return
  }

  const task = tasks.get(nextTaskId)
  if (!task) {
    refreshQueuedTasks()
    await runNextTask()
    return
  }

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
    refreshQueuedTasks()
    await runNextTask()
    return
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
    refreshQueuedTasks()
    await runNextTask()
    return
  }

  activeTaskId = task.id
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
  refreshQueuedTasks()

  const python = resolvePythonCommand(forgeRoot)
  const nvidiaBinPaths = resolveNvidiaBinPaths(forgeRoot)
  const args = [...python.args, ...buildProcessArgs(runnerScriptPath, task)]
  // O child process roda com stdout/stderr em pipe para alimentar a UI em tempo real.
  const child = spawn(python.command, args, {
    cwd: forgeRoot,
    env: {
      ...process.env,
      PATH: [...nvidiaBinPaths, process.env.PATH ?? ''].filter(Boolean).join(path.delimiter),
      PYTHONIOENCODING: 'utf-8',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  task.child = child

  let stdoutBuffer = ''
  let stderrBuffer = ''

  child.stdout.setEncoding('utf8')
  child.stderr.setEncoding('utf8')

  child.stdout.on('data', (chunk: string) => {
    stdoutBuffer += chunk
    stdoutBuffer = flushBuffer(stdoutBuffer, (line) => {
      const event = parseRunnerEvent(line)
      if (!event) {
        applyPlaintextRunnerLine(task, line)
        return
      }

      applyRunnerEvent(task, event)
    })
  })

  child.stderr.on('data', (chunk: string) => {
    stderrBuffer += chunk
    stderrBuffer = flushBuffer(stderrBuffer, (line) => {
      task.lastError = line
      console.error('[subtitle-service:stderr]', line)
    })
  })

  child.once('error', (error) => {
    task.lastError = error.message
  })

  child.once('close', async (code) => {
    if (stdoutBuffer.trim()) {
      const event = parseRunnerEvent(stdoutBuffer.trim())
      if (event) {
        applyRunnerEvent(task, event)
      } else {
        applyPlaintextRunnerLine(task, stdoutBuffer.trim())
      }
    }

    if (stderrBuffer.trim()) {
      task.lastError = stderrBuffer.trim().split(/\r?\n/).filter(Boolean).at(-1) ?? stderrBuffer.trim()
    }

    if (shouldRetryOnCpu(task)) {
      // Recoloca a task no topo da fila quando o ambiente GPU falha antes de desistir.
      task.child = null
      task.terminalEvent = null
      task.lastError = null
      task.options = {
        ...task.options,
        useCpu: true,
      }
      task.hasRetriedWithCpu = true
      task.status = 'queued'
      task.lastMessage = 'CUDA indisponivel. Tentando novamente em CPU...'
      activeTaskId = null
      queue.unshift(task.id)
      emitProgress(task, {
        status: 'queued',
        stage: 'retrying-cpu',
        message: task.lastMessage,
        progress: null,
        queuePosition: 1,
      })
      refreshQueuedTasks()
      await runNextTask()
      return
    }

    finishTask(task, code)
    task.child = null
    activeTaskId = null
    refreshQueuedTasks()
    await runNextTask()
  })
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
      child: null,
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
    queue.push(taskId)

    emitProgress(task, {
      status: 'queued',
      stage: 'queued',
      message: queue.length === 1 && !activeTaskId ? 'Aguardando inicializacao...' : `Na fila (${queue.length})`,
      progress: null,
      queuePosition: queue.length,
    })

    refreshQueuedTasks()
    await runNextTask()

    return taskId
  })

  // Cancela tanto tarefas ativas quanto itens que ainda estavam aguardando na fila.
  ipcMain.handle('subtitle:cancel', async (_event, taskId: string) => {
    const task = tasks.get(taskId)
    if (!task) {
      return false
    }

    if (task.child && activeTaskId === taskId) {
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
      task.child.kill()
      return true
    }

    const queuedIndex = queue.indexOf(taskId)
    if (queuedIndex >= 0) {
      queue.splice(queuedIndex, 1)
      task.status = 'cancelled'
      task.completedAt = Date.now()
      task.lastMessage = 'Tarefa removida da fila.'
      emitError(task, task.lastMessage, 'cancelled')
      refreshQueuedTasks()
      return true
    }

    return false
  })
}
