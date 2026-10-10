// Modo demonstracao (so em dev, com ?demo na URL): preenche a fila com exemplos e
// simula o preload do Electron. Serve pra tirar print e revisar layout sem GPU nem video.
import { useAppStore } from '@/store/appStore'
import type { StyleLibrary } from '@/types/subtitleStyle'
import type { ToolId } from '@/types/subtitle'

const now = Date.now()
const minutes = (value: number) => value * 60_000

const demoLibrary: StyleLibrary = {
  minVideos: 3,
  videos: [
    ['corte-susto-no-porao', 0.61, 0.58],
    ['react-trailer-gta-6', 0.72, 0.6],
    ['corte-chefe-final', 0.79, 0.57],
    ['shorts-bug-engracado', 0.83, 0.62],
  ].map(([name, before, formula], index) => ({
    id: `demo-video-${index}`,
    profile: 'vertical' as const,
    name: `${name}.mp4`,
    originalPath: `D:\\Gravacoes\\${name}.mp4`,
    taughtAt: now - minutes(60 * 24 * (6 - index)),
    f1Before: index === 0 ? null : Number(before),
    f1Formula: Number(formula),
    gapExamples: 180 + index * 37,
    timingSamples: 42 + index * 9,
  })),
  profiles: {
    vertical: {
      params: {
        min_words: 1,
        max_words: 4,
        max_card_ms: 2100,
        lead_in_ms: 80,
        hold_ms: 140,
        glue_ms: 260,
        min_card_ms: 420,
        videos: 4,
        gap_examples: 850,
      },
      tree: '|--- pausa_ms <= 210.00\n|   |--- palavras <= 3.50\n|   |   |--- class: junta\n|   |--- palavras >  3.50\n|   |   |--- class: quebra\n|--- pausa_ms >  210.00\n|   |--- class: quebra',
    },
  },
}

// Preload falso: tudo responde, nada roda. So entra quando o preload real nao existe.
function installFakeBridge() {
  const off = () => () => undefined
  window.clipforge = {
    window: {
      minimize: async () => undefined,
      maximize: async () => undefined,
      close: async () => undefined,
      focus: async () => undefined,
      requestAttention: async () => undefined,
    },
    dialog: { openFiles: async () => [], openDirectory: async () => null, getPathForFile: () => '' },
    shell: { showItemInFolder: async () => undefined, openPath: async () => '' },
    subtitle: {
      process: async () => 'demo',
      cancel: async () => false,
      onProgress: off,
      onDone: off,
      onError: off,
      burn: async () => 'demo',
      onBurnProgress: off,
      onBurnDone: off,
      onBurnError: off,
    },
    subtitleStyle: {
      list: async () => demoLibrary,
      learn: async () => ({ ok: false, error: 'Modo demonstração.' }),
      forget: async () => ({ ok: false, error: 'Modo demonstração.' }),
      onProgress: off,
    },
    clipSplitter: {
      process: async () => 'demo',
      cancel: async () => false,
      onProgress: off,
      onDone: off,
      onError: off,
    },
    cortes: {
      analyze: async () => 'demo',
      resegment: async () => false,
      cancel: async () => false,
      load: async () => null,
      generateXml: async () => ({ ok: false, error: 'Modo demonstração.' }),
      onProgress: off,
      onDone: off,
      onError: off,
    },
  }
}

// A store poe a tarefa mais nova em cima, entao os exemplos entram do mais velho pro mais novo.
function seedSubtitleQueue() {
  const store = useAppStore.getState()
  const common = { model: 'large-v3' as const, language: 'pt', device: 'cuda' as const }

  store.completeSubtitleTask({
    ...common,
    taskId: 'demo-done',
    filePath: 'D:\\Gravacoes\\shorts\\corte-susto-do-chefe.mp4',
    fileName: 'corte-susto-do-chefe.mp4',
    status: 'completed',
    stage: 'done',
    message: 'Legenda gerada.',
    progress: 100,
    outputPath: 'D:\\Gravacoes\\shorts\\corte-susto-do-chefe.srt',
    detectedLanguage: 'pt',
    processedSegments: 38,
    totalSegments: 38,
    startedAt: now - minutes(9),
    completedAt: now - minutes(8),
    durationSec: 41.3,
    translatedOutputs: { zh: 'D:\\Gravacoes\\shorts\\corte-susto-do-chefe.zh.srt' },
  })

  // Video solto em "Versao em chines": legenda pronta e a queima ja andando sozinha.
  store.completeSubtitleTask({
    ...common,
    taskId: 'demo-chinese',
    filePath: 'D:\\Gravacoes\\shorts\\corte-final-boss.mp4',
    fileName: 'corte-final-boss.mp4',
    status: 'completed',
    stage: 'done',
    message: 'Legenda gerada.',
    progress: 100,
    outputPath: 'D:\\Gravacoes\\shorts\\corte-final-boss.srt',
    detectedLanguage: 'pt',
    startedAt: now - minutes(4),
    completedAt: now - minutes(3),
    durationSec: 36.8,
    autoBurn: 'zh',
  })
  store.upsertHardsubJob({
    taskId: 'demo-chinese',
    jobId: 'demo-burn',
    mode: 'zh',
    format: 'shorts',
    status: 'processing',
    stage: 'burning',
    message: 'Queimando legenda... 62%',
    progress: 62,
  })

  // A fila de GPU roda um por vez: com a queima em chines rodando, a transcricao espera.
  store.upsertSubtitleProgress({
    ...common,
    taskId: 'demo-queued',
    filePath: 'D:\\Gravacoes\\resident-evil-requiem-ep03.mp4',
    fileName: 'resident-evil-requiem-ep03.mp4',
    status: 'queued',
    stage: 'queued',
    message: 'Aguardando a GPU.',
    progress: null,
    queuePosition: 1,
  })
}

function seedPreEditQueue() {
  const store = useAppStore.getState()
  const sourcePath = 'D:\\Gravacoes\\lives\\live-sexta-bruto.mkv'
  const outputDir = 'D:\\Gravacoes\\lives\\live-sexta-bruto_preedit'

  store.setClipSplitterSourcePath('D:\\Gravacoes\\lives\\live-sabado-bruto.mkv')
  store.completeClipSplitterTask({
    taskId: 'demo-preedit-done',
    sourcePath,
    sourceName: 'live-sexta-bruto.mkv',
    mode: 'silence',
    status: 'completed',
    stage: 'done',
    message: 'Pre-edicao concluida.',
    progress: 100,
    outputDir,
    clipsCreated: 1,
    totalClips: 1,
    sourceDurationSec: 11_520,
    startedAt: now - minutes(31),
    completedAt: now - minutes(12),
    durationSec: 1_134,
    clips: [
      {
        clipId: 'demo-clip',
        index: 1,
        filePath: `${outputDir}\\live-sexta-bruto_preedit.mp4`,
        fileName: 'live-sexta-bruto_preedit.mp4',
        startSec: 0,
        endSec: 9_684,
        durationSec: 9_684,
        reason: 'Pre-edicao unica com 1.284 pausa(s) analisada(s); 1836.0s removidos.',
        transcriptSnippet: 'Video limpo em ordem original para revisao manual.',
      },
    ],
  })
  store.upsertClipSplitterProgress({
    taskId: 'demo-preedit-queued',
    sourcePath: 'D:\\Gravacoes\\lives\\live-quinta-bruto.mkv',
    sourceName: 'live-quinta-bruto.mkv',
    mode: 'silence',
    status: 'queued',
    stage: 'queued',
    message: 'Aguardando a GPU.',
    progress: null,
    // Mesma fila de GPU das legendas: espera a queima e a transcricao.
    queuePosition: 2,
  })
}

const demoClipTitles: Array<[string, number]> = [
  ['Ele percebe que era tudo armação', 7.8],
  ['O plano dá errado logo de cara', 6.2],
  ['A cena do elevador', 8.9],
  ['Ninguém esperava essa volta', 5.4],
  ['Meu grito no susto', 9.3],
  ['A conversa que muda tudo', 4.7],
  ['Fuga pela cozinha', 6.8],
  ['O final do episódio', 7.1],
]

// Um react pronto (com lista de clipes) e outro esperando a mesma fila de GPU das outras ferramentas.
function seedCortesQueue() {
  const store = useAppStore.getState()
  const sourcePath = 'E:\\Bruto\\2026-07-28 23-40-19.mp4'
  let cursor = 144
  const clips = demoClipTitles.map(([title, score], index) => {
    const start = cursor
    cursor += 95 + ((index * 37) % 120)
    return { n: index + 1, start, end: cursor, title, hook: Math.round(score), score }
  })

  store.patchCortesSettings({ templatePath: 'D:\\Premiere\\molde-react.xml' })
  store.setCortesSourcePath('E:\\Bruto\\2026-08-02 22-10-05.mp4')
  store.upsertCortesEvent({
    taskId: 'demo-cortes-done',
    kind: 'analyze',
    sourcePath,
    sourceName: '2026-07-28 23-40-19.mp4',
    status: 'completed',
    stage: 'done',
    message: 'Analise pronta: 8 clipes.',
    progress: 100,
    startedAt: now - minutes(96),
    completedAt: now - minutes(6),
    durationSec: 5_412,
    warnings: ['Sem -hwaccel cuda: li o bruto na CPU (mais lento).'],
    analysis: {
      analysisPath: 'E:\\Bruto\\2026-07-28 23-40-19.cortes.json',
      sourcePath,
      durationSec: 7_298,
      start: 144,
      end: cursor,
      durations: { minSec: 70, targetSec: 150, maxSec: 240 },
      clips,
      warnings: ['Sem -hwaccel cuda: li o bruto na CPU (mais lento).'],
    },
  })
  store.upsertCortesEvent({
    taskId: 'demo-cortes-running',
    kind: 'analyze',
    sourcePath: 'E:\\Bruto\\2026-08-02 22-10-05.mp4',
    sourceName: '2026-08-02 22-10-05.mp4',
    status: 'queued',
    stage: 'queued',
    message: 'Na fila (3)',
    progress: null,
    // Atras da queima em chines e da pre-edicao: a GPU roda um job por vez.
    queuePosition: 3,
  })
}

// ?animate: a queima em chines (o unico job rodando na GPU) anda sozinha, pro video parecer vivo.
function animateQueue() {
  window.setInterval(() => {
    const store = useAppStore.getState()
    const burn = store.subtitleTasks.find((task) => task.id === 'demo-chinese')?.hardsubJobs.zh
    if (burn && (burn.progress ?? 0) < 99) {
      const progress = (burn.progress ?? 0) + 1
      store.upsertHardsubJob({
        taskId: 'demo-chinese',
        jobId: 'demo-burn',
        mode: 'zh',
        format: 'shorts',
        status: 'processing',
        stage: 'burning',
        message: `Queimando legenda... ${progress}%`,
        progress,
      })
    }
  }, 400)
}

export function installDemo(params: URLSearchParams) {
  if (!window.clipforge) {
    installFakeBridge()
  }
  seedSubtitleQueue()
  seedPreEditQueue()
  seedCortesQueue()

  // ?demo=clip-splitter abre direto no Pre-Editor; ?demo=cortes, nos Cortes.
  const tool = params.get('demo')
  if (tool === 'subtitle-forge' || tool === 'clip-splitter' || tool === 'cortes') {
    useAppStore.getState().setActiveTool(tool satisfies ToolId)
  }
  if (params.get('format') === 'shorts') {
    useAppStore.getState().patchSubtitleSettings({ format: 'shorts', maxWords: 3, uppercase: true })
  }
  if (params.has('animate')) {
    animateQueue()
  }
}
