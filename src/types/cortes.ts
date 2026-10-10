// Contrato entre a tela de Cortes e o processo principal (src/types e importado pelos dois lados).
export type CortesTaskStatus = 'queued' | 'preparing' | 'processing' | 'completed' | 'error' | 'cancelled'
// analyze le o bruto inteiro; resegment so refaz as fronteiras com outra duracao.
export type CortesJobKind = 'analyze' | 'resegment'

export interface CortesDurations {
  minSec: number
  targetSec: number
  maxSec: number
}

// O que o Inspetor lembra entre aberturas.
export interface CortesSettings extends CortesDurations {
  // XML exportado do Premiere com um clipe montado ('' = ainda nao escolhido).
  templatePath: string
  // Faixas de audio do bruto, 1 = primeira.
  filmTrack: number
  micTrack: number
  titlesWithAi: boolean
}

export interface CortesAnalyzeOptions extends CortesDurations {
  // Trecho opcional (2:24.44, 1:58:00); vazio = do comeco / ate o fim.
  start: string
  end: string
  filmTrack: number
  micTrack: number
  titlesWithAi: boolean
}

export interface CortesResegmentRequest extends CortesDurations {
  sourcePath: string
  analysisPath: string
  titlesWithAi: boolean
}

export interface CortesClip {
  n: number
  start: number
  end: number
  title: string
  hook: number | null
  score: number | null
}

// Resumo do <bruto>.cortes.json (a transcricao fica de fora: e grande e a tela nao usa).
export interface CortesAnalysisSummary {
  analysisPath: string
  sourcePath: string
  durationSec: number
  // Trecho analisado, em segundos no bruto.
  start: number
  end: number
  durations: CortesDurations
  clips: CortesClip[]
  warnings: string[]
}

export interface CortesXmlRequest {
  analysisPath: string
  templatePath: string
  clips: number[]
}

export type CortesXmlResult = { ok: true; outputPath: string } | { ok: false; error: string }

export interface CortesTaskEventBase {
  taskId: string
  kind: CortesJobKind
  sourcePath: string
  sourceName: string
  status: CortesTaskStatus
  stage: string
  message: string
  progress: number | null
  queuePosition?: number
  warnings?: string[]
  analysis?: CortesAnalysisSummary
  startedAt?: number
  completedAt?: number
  durationSec?: number
}

export type CortesProgressEvent = CortesTaskEventBase

export interface CortesDoneEvent extends CortesTaskEventBase {
  status: 'completed'
  progress: 100
  completedAt: number
  durationSec: number
  analysis: CortesAnalysisSummary
}

export interface CortesErrorEvent extends CortesTaskEventBase {
  status: 'error' | 'cancelled'
  error: string
}

export interface CortesXmlState {
  status: 'running' | 'done' | 'error'
  outputPath: string | null
  error: string | null
}

export interface CortesTask {
  id: string
  kind: CortesJobKind
  sourcePath: string
  sourceName: string
  status: CortesTaskStatus
  stage: string
  message: string
  progress: number | null
  queuePosition: number | null
  warnings: string[]
  analysis: CortesAnalysisSummary | null
  // Opcoes da analise, pra "Tentar de novo" repetir igual.
  request: CortesAnalyzeOptions | null
  createdAt: number
  startedAt: number | null
  completedAt: number | null
  durationSec: number | null
  error: string | null
  xml: CortesXmlState | null
}
