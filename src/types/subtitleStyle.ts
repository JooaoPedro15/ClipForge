// Contrato IPC do aprendizado de estilo de legenda (o Electron importa daqui).

// Um perfil por orientacao do video: o estilo de Shorts e de video longo e diferente.
export type StyleProfileName = 'vertical' | 'horizontal'

// Minimo de videos ensinados pra geracao usar o perfil (igual a style_model.MIN_VIDEOS_FOR_MODEL).
export const STYLE_MIN_VIDEOS = 3

export interface StyleVideoEntry {
  id: string
  profile: StyleProfileName
  name: string
  originalPath: string
  taughtAt: number
  // Acerto de quebra do perfil ANTES de aprender com este video (null = perfil ainda nao existia).
  f1Before: number | null
  // Acerto da formula antiga neste video, como referencia.
  f1Formula: number
  gapExamples: number
  timingSamples: number
}

// params.json do perfil (nomes como o Python grava).
export interface StyleProfileParams {
  min_words: number
  max_words: number
  max_card_ms: number
  lead_in_ms: number
  hold_ms: number
  glue_ms: number
  min_card_ms: number
  videos: number
  gap_examples: number
}

export interface StyleProfileSummary {
  params: StyleProfileParams
  // Arvore em texto (export_text do scikit-learn): as "regras" do usuario.
  tree: string
}

export interface StyleLibrary {
  videos: StyleVideoEntry[]
  profiles: Partial<Record<StyleProfileName, StyleProfileSummary>>
  minVideos: number
}

export interface StyleLearnRequest {
  originalPath: string
  // SRT corrigido ou projeto do Premiere (.prproj); no projeto, `sequence` diz qual sequencia.
  srtPath: string
  sequence?: string | null
  finalPath: string
  model: string
  language: string
  useCpu: boolean
}

// Sequencia com legenda achada num .prproj; caminhos ficam null quando o projeto nao diz qual e.
export interface StyleProjectSequence {
  name: string
  cards: number
  finalPath: string | null
  originalPath: string | null
}

export interface StyleProjectScan {
  projectPath: string
  sequences: StyleProjectSequence[]
}

// Ensinar pelo projeto: todas as sequencias completas, ou so `only` (o botao "Ensinar <sequencia>").
export interface StyleProjectLearnRequest {
  projectPath: string
  // Pastas ou arquivos dos brutos: Sequencia 43.mp3 casa com a sequencia "Sequencia 43".
  originals: string[]
  // Videos finais escolhidos (nome livre): casados pelo conteudo quando o projeto nao diz qual e.
  finals: string[]
  only?: string | null
  model: string
  language: string
  useCpu: boolean
}

export interface StyleProjectLearnReport {
  taught: Array<StyleReport & { name: string }>
  skipped: Array<{ name: string; reason: string }>
  failed: Array<{ name: string; error: string }>
}

export interface StyleReport {
  videoId: string
  profile: StyleProfileName
  f1Before: number | null
  f1Formula: number
  f1After: number | null
  gapExamples: number
  timingSamples: number
  // Parte do video bruto (0 a 1) cortada no Premiere: ignorada no aprendizado, nao conta como erro.
  cutShare: number
  warnings: string[]
}

export interface StyleForgetReport {
  videoId: string
  profile: StyleProfileName
}

export type StyleRunResult<T> = { ok: true; report: T } | { ok: false; error: string }

export interface StyleProgressEvent {
  stage: string
  message: string
  progress: number | null
}
