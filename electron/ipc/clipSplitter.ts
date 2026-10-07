import crypto from 'node:crypto'
import path from 'node:path'

import { ipcMain, type WebContents } from 'electron'

import { resolveProjectRoot, resolveScriptPath } from '../python/pythonEnv.js'
import { runPython, type PythonRun } from '../python/pythonProcess.js'
import { decideOutcome, describeExitCode, looksLikeGpuFailure, parseRunnerLine } from '../python/runnerEvents.js'

// Tipos locais que descrevem os jobs do Pre-Editor enquanto rodam no processo principal.
type ClipSplitterMode = 'fixed' | 'silence'
type ClipSplitterPreEditMode = 'conservative' | 'balanced' | 'aggressive'
type ClipSplitterStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'

interface ClipSplitterTaskOptions {
  mode: ClipSplitterMode
  preEditMode: ClipSplitterPreEditMode
  writeDebugJson: boolean
  analysisAudioTrack: string
  targetDurationSec: number
  minClipDurationSec: number
  maxClipDurationSec: number
  silenceThresholdDb: number
  silenceMinDurationSec: number
  outputDir?: string | null
}

interface ClipExportPayload {
  clipId: string
  index: number
  filePath: string
  fileName: string
  startSec: number
  endSec: number
  durationSec: number
  reason: string
  transcriptSnippet: string
}

interface ClipSplitterEventPayload {
  taskId: string
  sourcePath: string
  sourceName: string
  mode: ClipSplitterMode
  status: ClipSplitterStatus
  stage: string
  message: string
  progress: number | null
  queuePosition?: number
  outputDir?: string | null
  debugPath?: string | null
  clipsCreated?: number
  totalClips?: number
  sourceDurationSec?: number
  startedAt?: number
  completedAt?: number
  durationSec?: number
  clips?: ClipExportPayload[]
}

interface ClipSplitterErrorPayload extends ClipSplitterEventPayload {
  error: string
}

interface RunnerStatusEvent {
  event: 'status'
  status: 'preparing' | 'processing'
  stage: string
  message: string
  progress?: number | null
  outputDir?: string | null
  debugPath?: string | null
  clipsCreated?: number
  totalClips?: number
  sourceDurationSec?: number
  durationSec?: number
  clips?: ClipExportPayload[]
}

interface RunnerDoneEvent {
  event: 'done'
  status: 'completed'
  stage: string
  message: string
  progress?: number | null
  outputDir?: string | null
  debugPath?: string | null
  clipsCreated?: number
  totalClips?: number
  sourceDurationSec?: number
  durationSec?: number
  clips?: ClipExportPayload[]
}

interface RunnerErrorEvent {
  event: 'error'
  status: 'error'
  stage: string
  message: string
  error: string
  progress?: number | null
  outputDir?: string | null
  debugPath?: string | null
  clipsCreated?: number
  totalClips?: number
  sourceDurationSec?: number
  clips?: ClipExportPayload[]
}

type RunnerEvent = RunnerStatusEvent | RunnerDoneEvent | RunnerErrorEvent

const RUNNER_EVENTS = ['status', 'done', 'error'] as const

interface ClipSplitterTaskRecord {
  id: string
  sender: WebContents
  sourcePath: string
  sourceName: string
  options: ClipSplitterTaskOptions
  useCpu: boolean
  status: ClipSplitterStatus
  outputDir: string | null
  debugPath: string | null
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  process: PythonRun | null
  cancelRequested: boolean
  clipsCreated: number
  totalClips: number | null
  sourceDurationSec: number | null
  lastMessage: string
  lastError: string | null
  terminalEvent: RunnerDoneEvent | RunnerErrorEvent | null
  hasRetriedWithCpu: boolean
  clips: ClipExportPayload[]
}

// Estruturas em memoria da fila de exportacao e do job atualmente ativo.
const tasks = new Map<string, ClipSplitterTaskRecord>()
const queue: string[] = []

let activeTaskId: string | null = null

const defaultOptions: ClipSplitterTaskOptions = {
  mode: 'silence',
  preEditMode: 'balanced',
  writeDebugJson: false,
  analysisAudioTrack: '1',
  targetDurationSec: 35,
  minClipDurationSec: 20,
  maxClipDurationSec: 50,
  silenceThresholdDb: -35,
  silenceMinDurationSec: 0.45,
  outputDir: null,
}

// Corrige limites de duracao e limpa valores antes de iniciar um novo job.
function normalizeOptions(options: Partial<ClipSplitterTaskOptions> | undefined): ClipSplitterTaskOptions {
  const minClipDurationSec = Math.max(5, Number(options?.minClipDurationSec ?? defaultOptions.minClipDurationSec))
  const maxClipDurationSec = Math.max(
    minClipDurationSec + 1,
    Number(options?.maxClipDurationSec ?? defaultOptions.maxClipDurationSec),
  )
  const targetDurationSec = Math.min(
    maxClipDurationSec,
    Math.max(minClipDurationSec, Number(options?.targetDurationSec ?? defaultOptions.targetDurationSec)),
  )

  return {
    ...defaultOptions,
    ...options,
    mode: options?.mode === 'fixed' ? 'fixed' : 'silence',
    preEditMode:
      options?.preEditMode === 'conservative' || options?.preEditMode === 'aggressive'
        ? options.preEditMode
        : defaultOptions.preEditMode,
    writeDebugJson: options?.writeDebugJson ?? defaultOptions.writeDebugJson,
    analysisAudioTrack: String(options?.analysisAudioTrack ?? defaultOptions.analysisAudioTrack).trim() || defaultOptions.analysisAudioTrack,
    targetDurationSec,
    minClipDurationSec,
    maxClipDurationSec,
    silenceThresholdDb: Number(options?.silenceThresholdDb ?? defaultOptions.silenceThresholdDb),
    silenceMinDurationSec: Math.max(0.1, Number(options?.silenceMinDurationSec ?? defaultOptions.silenceMinDurationSec)),
    outputDir: options?.outputDir?.trim() || null,
  }
}

// Envia eventos para o renderer somente quando a janela ainda esta valida.
function emit(
  sender: WebContents,
  channel: 'clipSplitter:progress' | 'clipSplitter:done' | 'clipSplitter:error',
  payload: ClipSplitterEventPayload | ClipSplitterErrorPayload,
) {
  if (!sender.isDestroyed()) {
    sender.send(channel, payload)
  }
}

// Monta o payload base que o frontend usa para renderizar o estado do job.
function toPayload(task: ClipSplitterTaskRecord, overrides: Partial<ClipSplitterEventPayload>): ClipSplitterEventPayload {
  return {
    taskId: task.id,
    sourcePath: task.sourcePath,
    sourceName: task.sourceName,
    mode: task.options.mode,
    status: task.status,
    stage: 'idle',
    message: task.lastMessage,
    progress: null,
    outputDir: task.outputDir,
    debugPath: task.debugPath,
    clipsCreated: task.clipsCreated,
    totalClips: task.totalClips ?? undefined,
    sourceDurationSec: task.sourceDurationSec ?? undefined,
    startedAt: task.startedAt ?? undefined,
    completedAt: task.completedAt ?? undefined,
    clips: task.clips.length > 0 ? task.clips : undefined,
    ...overrides,
  }
}

// Helpers de emissao para reduzir duplicacao entre progresso, done e error.
function emitProgress(task: ClipSplitterTaskRecord, overrides: Partial<ClipSplitterEventPayload>) {
  emit(task.sender, 'clipSplitter:progress', toPayload(task, overrides))
}

function emitDone(task: ClipSplitterTaskRecord, durationSec: number) {
  emit(task.sender, 'clipSplitter:done', {
    ...toPayload(task, {
      status: 'completed',
      stage: 'done',
      message: task.lastMessage || 'Pre-Editor concluido.',
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

function emitError(task: ClipSplitterTaskRecord, message: string, status: 'error' | 'cancelled') {
  const payload: ClipSplitterErrorPayload = {
    ...toPayload(task, {
      status,
      stage: status,
      message,
      completedAt: task.completedAt ?? Date.now(),
    }),
    status,
    error: message,
  }

  emit(task.sender, 'clipSplitter:error', payload)
}

function refreshQueuedTasks() {
  // Atualiza a posicao de fila de todos os jobs ainda nao iniciados.
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

// Descobre onde esta o projeto externo Clip-Splitter e seu ambiente Python.
function resolveClipSplitterRoot() {
  return resolveProjectRoot(
    [process.env.CLIPFORGE_CLIP_SPLITTER_PATH, path.resolve(process.cwd(), '../Clip-Splitter'), 'D:\\Projetos\\Clip-Splitter'],
    'clip_splitter.py',
  )
}

// Localiza o runner Python mantido dentro deste repo.
function resolveRunnerScriptPath() {
  return resolveScriptPath([
    path.resolve(process.cwd(), 'python', 'clip_splitter_service.py'),
    path.resolve(process.cwd(), '..', 'clip-forge', 'python', 'clip_splitter_service.py'),
  ]).scriptPath
}

// Converte o estado da tarefa em argumentos CLI aceitos pelo service Python.
function buildProcessArgs(serviceScriptPath: string, clipSplitterRoot: string, task: ClipSplitterTaskRecord) {
  const args = [
    serviceScriptPath,
    task.sourcePath,
    '--project-root',
    clipSplitterRoot,
    '--mode',
    task.options.mode,
    '--preedit-mode',
    task.options.preEditMode,
    '--target-duration',
    String(task.options.targetDurationSec),
    '--min-duration',
    String(task.options.minClipDurationSec),
    '--max-duration',
    String(task.options.maxClipDurationSec),
    '--silence-threshold-db',
    String(task.options.silenceThresholdDb),
    '--silence-min-duration',
    String(task.options.silenceMinDurationSec),
    '--analysis-audio-track',
    task.options.analysisAudioTrack,
  ]

  if (task.useCpu) {
    args.push('--cpu')
  }

  if (task.options.writeDebugJson) {
    args.push('--write-debug-json')
  }

  if (task.options.outputDir) {
    args.push('--output', task.options.outputDir)
  }

  return args
}

// Detecta quando o stdout trouxe um evento JSON estruturado do runner.
function parseRunnerEvent(line: string): RunnerEvent | null {
  return parseRunnerLine<RunnerEvent>(line, RUNNER_EVENTS)
}

// Aproveita logs livres do runner para atualizar mensagem e pasta de saida.
function applyPlaintextRunnerLine(task: ClipSplitterTaskRecord, line: string) {
  task.lastMessage = line

  const outputMatch = line.match(/saida:\s*(.+)$/i)
  if (outputMatch?.[1]) {
    task.outputDir = outputMatch[1].trim()
  }

  emitProgress(task, {
    status: task.status,
    stage: 'log',
    message: task.lastMessage,
    progress: null,
    outputDir: task.outputDir,
    clipsCreated: task.clipsCreated,
    totalClips: task.totalClips ?? undefined,
    sourceDurationSec: task.sourceDurationSec ?? undefined,
  })
}

// Aplica eventos estruturados ao estado em memoria do job e dos clipes exportados.
function applyRunnerEvent(task: ClipSplitterTaskRecord, event: RunnerEvent) {
  task.lastMessage = event.message

  if (typeof event.clipsCreated === 'number') {
    task.clipsCreated = event.clipsCreated
  }

  if (typeof event.totalClips === 'number') {
    task.totalClips = event.totalClips
  }

  if (typeof event.outputDir === 'string') {
    task.outputDir = event.outputDir
  }

  if (typeof event.debugPath === 'string') {
    task.debugPath = event.debugPath
  }

  if (typeof event.sourceDurationSec === 'number') {
    task.sourceDurationSec = event.sourceDurationSec
  }

  if (Array.isArray(event.clips)) {
    task.clips = event.clips
  }

  if (event.event === 'status') {
    task.status = event.status
    emitProgress(task, {
      status: event.status,
      stage: event.stage,
      message: event.message,
      progress: event.progress ?? null,
      outputDir: task.outputDir,
      debugPath: task.debugPath,
      clipsCreated: task.clipsCreated,
      totalClips: task.totalClips ?? undefined,
      sourceDurationSec: task.sourceDurationSec ?? undefined,
      queuePosition: undefined,
    })
    return
  }

  task.terminalEvent = event
}

// Consolida o desfecho do job quando o processo filho encerra.
function finishTask(task: ClipSplitterTaskRecord, code: number | null) {
  task.completedAt = Date.now()
  const fallbackDurationSec = task.startedAt ? Number(((task.completedAt - task.startedAt) / 1000).toFixed(1)) : 0
  const outcome = decideOutcome({
    cancelRequested: task.cancelRequested,
    terminalEvent: task.terminalEvent,
    code,
    lastError: task.lastError,
    lastMessage: task.lastMessage,
    defaultDoneMessage: 'Pre-Editor concluido.',
    describeExit: (exitCode) => describeExitCode(exitCode, 'Pre-Editor'),
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

// Decide se um erro tem cara de falha de GPU e merece retry em CPU.
function shouldRetryOnCpu(task: ClipSplitterTaskRecord, code: number | null) {
  if (task.useCpu || task.hasRetriedWithCpu) {
    return false
  }

  return looksLikeGpuFailure(`${task.lastError ?? ''}\n${task.lastMessage}`, code)
}

// Motor da fila de exportacao: inicia o proximo job, acompanha logs e encadeia retries.
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

  const clipSplitterRoot = resolveClipSplitterRoot()
  if (!clipSplitterRoot) {
    task.status = 'error'
    task.completedAt = Date.now()
    task.lastMessage = 'Projeto Clip-Splitter nao encontrado.'
    emitError(
      task,
      'Projeto Clip-Splitter nao encontrado. Configure em D:\\Projetos\\Clip-Splitter ou use CLIPFORGE_CLIP_SPLITTER_PATH.',
      'error',
    )
    refreshQueuedTasks()
    await runNextTask()
    return
  }

  const runnerScriptPath = resolveRunnerScriptPath()
  if (!runnerScriptPath) {
    task.status = 'error'
    task.completedAt = Date.now()
    task.lastMessage = 'Runner do Pre-Editor nao encontrado.'
    emitError(task, `${task.lastMessage} Verifique python/clip_splitter_service.py.`, 'error')
    refreshQueuedTasks()
    await runNextTask()
    return
  }

  activeTaskId = task.id
  task.status = 'preparing'
  task.startedAt = Date.now()
  task.lastMessage = task.useCpu
    ? 'Inicializando Pre-Editor com Whisper em CPU...'
    : 'Inicializando Pre-Editor em modo local...'

  emitProgress(task, {
    status: 'preparing',
    stage: 'starting',
    message: task.lastMessage,
    progress: 5,
    queuePosition: undefined,
  })
  refreshQueuedTasks()

  const run = runPython({
    root: clipSplitterRoot,
    scriptArgs: buildProcessArgs(runnerScriptPath, clipSplitterRoot, task),
    extraEnv: { CLIPFORGE_CLIP_SPLITTER_PATH: clipSplitterRoot },
    logTag: 'clip-splitter-service',
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

  void run.done.then(async ({ code, spawnError, lastStderrLine }) => {
    if (spawnError && !lastStderrLine) {
      task.lastError = spawnError
    }

    if (shouldRetryOnCpu(task, code)) {
      // Em falhas tipicas de CUDA, o mesmo job volta ao topo da fila usando CPU.
      task.process = null
      task.terminalEvent = null
      task.lastError = null
      task.useCpu = true
      task.hasRetriedWithCpu = true
      task.status = 'queued'
      task.lastMessage = 'Falha no caminho CUDA. Tentando novamente em CPU...'
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
    task.process = null
    activeTaskId = null
    refreshQueuedTasks()
    await runNextTask()
  })
}

export function registerClipSplitterHandlers() {
  // Registra a criacao de jobs de corte/exportacao vindos do renderer.
  ipcMain.handle('clipSplitter:process', async (event, sourcePath: string, options?: Partial<ClipSplitterTaskOptions>) => {
    const resolvedOptions = normalizeOptions(options)
    const taskId = crypto.randomUUID()
    const sourceName = path.basename(sourcePath)

    const task: ClipSplitterTaskRecord = {
      id: taskId,
      sender: event.sender,
      sourcePath,
      sourceName,
      options: resolvedOptions,
      useCpu: false,
      status: 'queued',
      outputDir: resolvedOptions.outputDir ?? null,
      debugPath: null,
      createdAt: Date.now(),
      startedAt: null,
      completedAt: null,
      process: null,
      cancelRequested: false,
      clipsCreated: 0,
      totalClips: null,
      sourceDurationSec: null,
      lastMessage: 'Tarefa adicionada a fila.',
      lastError: null,
      terminalEvent: null,
      hasRetriedWithCpu: false,
      clips: [],
    }

    tasks.set(taskId, task)
    queue.push(taskId)

    emitProgress(task, {
      status: 'queued',
      stage: 'queued',
      message: queue.length === 1 && !activeTaskId ? 'Aguardando inicializacao...' : `Na fila (${queue.length})`,
      progress: null,
      queuePosition: queue.length,
      outputDir: task.outputDir,
    })

    refreshQueuedTasks()
    await runNextTask()

    return taskId
  })

  // Permite cancelar tanto jobs ativos quanto itens ainda nao iniciados.
  ipcMain.handle('clipSplitter:cancel', async (_event, taskId: string) => {
    const task = tasks.get(taskId)
    if (!task) {
      return false
    }

    task.cancelRequested = true

    const queueIndex = queue.findIndex((queuedTaskId) => queuedTaskId === taskId)
    if (queueIndex >= 0) {
      queue.splice(queueIndex, 1)
      task.status = 'cancelled'
      task.completedAt = Date.now()
      task.lastMessage = 'Tarefa cancelada antes de iniciar.'
      emitError(task, task.lastMessage, 'cancelled')
      refreshQueuedTasks()
      return true
    }

    if (task.process) {
      task.process.kill()
      return true
    }

    return false
  })
}
