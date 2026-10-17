// Contrato entre a tela da Pre-edicao que aprende e o processo principal (importado pelos dois lados).
export type PreeditTaskStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'
// edit gera o XML dos brutos; os ensinos alimentam a biblioteca.
export type PreeditJobKind = 'edit' | 'teach-projects' | 'teach-finals'
// aproximando: o zoom entra no rosto e continua chegando perto; seco: zoom parado.
export type PreeditZoomStyle = 'aproximando' | 'seco'

export interface PreeditEditRequest {
  // Arquivos de uma gravacao (pausada no OBS), na ordem em que entram na sequencia.
  recordings: string[]
  minutes: number
  // XML exportado do Premiere ('' = sem molde: sequencia do tamanho da gravacao, sem zoom).
  moldePath: string
  zoomStyle: PreeditZoomStyle
}

export interface PreeditTeachProjectsRequest {
  projects: string[]
}

export interface PreeditTeachFinalsRequest {
  projectsDir: string
  videosDir: string
}

// O pedido de cada item, pra "Tentar de novo" repetir igual.
export type PreeditJobRequest =
  | { kind: 'edit'; request: PreeditEditRequest }
  | { kind: 'teach-projects'; request: PreeditTeachProjectsRequest }
  | { kind: 'teach-finals'; request: PreeditTeachFinalsRequest }

export interface PreeditTaskEvent {
  taskId: string
  kind: PreeditJobKind
  title: string
  status: PreeditTaskStatus
  stage: string
  message: string
  progress: number | null
  queuePosition?: number
  warnings: string[]
  // Relatorio do Python no fim (edit: xmlPath, durationSec...; ensino: taught, skipped, failed...).
  result?: Record<string, unknown>
  error?: string
  startedAt?: number
  completedAt?: number
}

export interface PreeditFormatCounts {
  longo: number
  short: number
}

export interface PreeditLibrary {
  // Gravacoes ensinadas com o bruto (ensinam cortes e zoom) e videos prontos (so zoom).
  recordings: PreeditFormatCounts
  finals: PreeditFormatCounts
  // O editor do video longo ja tem modelos treinados.
  editorReady: boolean
}

export type PreeditLibraryResult = { ok: true; library: PreeditLibrary } | { ok: false; error: string }

export interface PreeditTask extends PreeditTaskEvent {
  id: string
  request: PreeditJobRequest | null
  createdAt: number
}

// O que a tela lembra entre aberturas.
export interface PreeditSettings {
  // learn: a Pre-edicao que aprende; voice: o corte por voz antigo.
  mode: 'learn' | 'voice'
  minutes: number
  zoomStyle: PreeditZoomStyle
  moldePath: string
}
