// Identifica as ferramentas disponiveis no shell principal do app.
export type ToolId = 'subtitle-forge' | 'clip-splitter'

// Modelos Whisper expostos no seletor da interface.
export type SubtitleModel = 'tiny' | 'base' | 'small' | 'medium' | 'large-v3'

// Estados que uma tarefa pode assumir enquanto passa pela fila e pelo runner.
export type SubtitleTaskStatus =
  | 'queued'
  | 'preparing'
  | 'processing'
  | 'completed'
  | 'error'
  | 'cancelled'

export type HardsubMode = 'zh' | 'zh-en' | 'zh-original'
export type HardsubFormat = 'shorts' | 'long'
export type HardsubJobStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'

export interface HardsubJobState {
  status: HardsubJobStatus
  stage: string
  message: string
  progress: number | null
  outputPath: string | null
  error: string | null
}

export interface HardsubEvent {
  taskId: string
  jobId: string
  mode: HardsubMode
  format: HardsubFormat
  status: HardsubJobStatus
  stage: string
  message: string
  progress: number | null
  outputPath?: string | null
  error?: string
}

export interface SubtitleTaskOptions {
  // Preferencias enviadas do renderer para o processo Electron/Python.
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
  // Contexto livre do video ("gameplay de terror", "reacao"), usado pela traducao.
  videoType: string
  format: HardsubFormat
  outputPath?: string | null
}

export interface SubtitleTaskEventBase {
  // Estrutura comum dos eventos que trafegam do backend para o renderer.
  taskId: string
  filePath: string
  fileName: string
  model: SubtitleModel
  language: string
  device: 'cpu' | 'cuda'
  status: SubtitleTaskStatus
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

// Evento intermediario de progresso emitido durante o processamento.
export interface SubtitleProgressEvent extends SubtitleTaskEventBase {}

export interface SubtitleDoneEvent extends SubtitleTaskEventBase {
  // Evento final emitido quando a transcricao conclui com sucesso.
  status: 'completed'
  progress: 100
  completedAt: number
  durationSec: number
}

export interface SubtitleErrorEvent extends SubtitleTaskEventBase {
  // Evento final emitido quando a tarefa falha ou e cancelada.
  status: 'error' | 'cancelled'
  error: string
}

export interface SubtitleTask {
  // Representacao persistida na store para alimentar a interface do SubtitleForge.
  id: string
  filePath: string
  fileName: string
  outputPath: string | null
  model: SubtitleModel
  language: string
  detectedLanguage: string | null
  device: 'cpu' | 'cuda'
  status: SubtitleTaskStatus
  stage: string
  message: string
  progress: number | null
  queuePosition: number | null
  processedSegments: number
  totalSegments: number | null
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  durationSec: number | null
  error: string | null
  translatedOutputs: Record<string, string>
  translationErrors: Record<string, string>
  hardsubJobs: Partial<Record<HardsubMode, HardsubJobState>>
}
