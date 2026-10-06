// Modo base usado pelo algoritmo de corte.
export type ClipSplitterMode = 'fixed' | 'silence'
// Intensidade da pre-edicao de pausas no modo silencio.
export type ClipSplitterPreEditMode = 'conservative' | 'balanced' | 'aggressive'
// Rotulos de feedback manual usados para memoria local dos clipes.
export type ClipFeedbackLabel = 'weak' | 'good' | 'viral'

// Estados possiveis de um job do Pre-Editor.
export type ClipSplitterTaskStatus =
  | 'queued'
  | 'preparing'
  | 'processing'
  | 'completed'
  | 'error'
  | 'cancelled'

export interface ClipSplitterOptions {
  // Configuracoes enviadas para o processo de corte/exportacao.
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

export interface ClipSplitterClip {
  // Metadados do clipe exportado mostrados na UI e salvos para feedback.
  clipId: string
  index: number
  filePath: string
  fileName: string
  startSec: number
  endSec: number
  durationSec: number
  reason: string
  transcriptSnippet: string
  feedbackLabel?: ClipFeedbackLabel | null
  feedbackUpdatedAt?: number | null
}

export interface ClipSplitterTaskEventBase {
  // Campos base compartilhados pelos eventos do runner de corte.
  taskId: string
  sourcePath: string
  sourceName: string
  mode: ClipSplitterMode
  status: ClipSplitterTaskStatus
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
  clips?: ClipSplitterClip[]
}

// Evento emitido durante planejamento e exportacao dos clipes.
export interface ClipSplitterProgressEvent extends ClipSplitterTaskEventBase {}

export interface ClipSplitterDoneEvent extends ClipSplitterTaskEventBase {
  // Evento final quando o job termina com sucesso.
  status: 'completed'
  progress: 100
  completedAt: number
  durationSec: number
}

export interface ClipSplitterErrorEvent extends ClipSplitterTaskEventBase {
  // Evento final usado para falha tecnica ou cancelamento.
  status: 'error' | 'cancelled'
  error: string
}

export interface ClipSplitterTask {
  // Estrutura usada pela store para renderizar cada job do Pre-Editor.
  id: string
  sourcePath: string
  sourceName: string
  mode: ClipSplitterMode
  status: ClipSplitterTaskStatus
  stage: string
  message: string
  progress: number | null
  queuePosition: number | null
  outputDir: string | null
  debugPath: string | null
  clipsCreated: number
  totalClips: number | null
  sourceDurationSec: number | null
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  durationSec: number | null
  error: string | null
  clips: ClipSplitterClip[]
}
