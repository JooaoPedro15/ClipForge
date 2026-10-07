import { HardDriveDownload, Layers3, SlidersHorizontal } from 'lucide-react'

import { DropZone } from '@/components/subtitle/DropZone'
import { StatsBar } from '@/components/subtitle/StatsBar'
import { TaskList } from '@/components/subtitle/TaskList'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { CustomSelect } from '@/components/ui/CustomSelect'
import { Toggle } from '@/components/ui/Toggle'
import { useAppStore } from '@/store/appStore'
import type { HardsubMode } from '@/types/subtitle'

interface SubtitleForgePageProps {
  onPickFiles: () => Promise<{ ok: boolean; message: string | null }>
  onDropPaths: (paths: string[]) => Promise<{ ok: boolean; message: string | null }>
  onCancelTask: (taskId: string) => void
  onOpenOutput: (outputPath: string | null) => void
  onRetryTask: (filePath: string) => void
  onBurn: (taskId: string, mode: HardsubMode) => void
}

export function SubtitleForgePage({
  onPickFiles,
  onDropPaths,
  onCancelTask,
  onOpenOutput,
  onRetryTask,
  onBurn,
}: SubtitleForgePageProps) {
  // Busca as tarefas e configuracoes da transcricao direto da store global.
  const tasks = useAppStore((state) => state.subtitleTasks)
  const settings = useAppStore((state) => state.subtitleSettings)
  const patchSettings = useAppStore((state) => state.patchSubtitleSettings)
  const setOutputPath = useAppStore((state) => state.setSubtitleOutputPath)

  return (
    <div className="space-y-6">
      {/* Resumo rapido do estado atual da fila de transcricao. */}
      <StatsBar tasks={tasks} />

      <div className="grid gap-6 2xl:grid-cols-[1.3fr_0.9fr]">
        <div className="space-y-6">
          {/* Entrada principal para drag and drop ou selecao manual de arquivos. */}
          <DropZone onDropPaths={onDropPaths} onPickFiles={onPickFiles} />
          {/* Lista detalhada das tarefas ja enviadas para o backend Python. */}
          <TaskList
            onBurn={onBurn}
            onCancel={onCancelTask}
            onOpenOutput={onOpenOutput}
            onRetry={onRetryTask}
            tasks={tasks}
          />
        </div>

        <div className="space-y-6">
          <Card className="space-y-5">
            <div className="flex items-center justify-between gap-4">
              <div>
                <h3 className="text-xl font-semibold text-text-primary">Configuração da transcrição</h3>
                <p className="mt-1 text-sm text-text-secondary">Ajustes do modelo Whisper para este preset.</p>
              </div>
              <Badge tone={settings.useCpu ? 'yellow' : 'green'}>{settings.useCpu ? 'CPU' : 'GPU'}</Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              {/* Parametros que controlam o modelo Whisper e o formato do texto final. */}
              <div className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Modelo</span>
                <CustomSelect
                  value={settings.model}
                  onChange={(value) => patchSettings({ model: value as typeof settings.model })}
                  options={[
                    { value: 'tiny', label: 'tiny' },
                    { value: 'base', label: 'base' },
                    { value: 'small', label: 'small' },
                    { value: 'medium', label: 'medium' },
                    { value: 'large-v3', label: 'large-v3' },
                  ]}
                />
              </div>

              <div className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Formato</span>
                <CustomSelect
                  value={settings.format}
                  onChange={(value) => {
                    const format = value as typeof settings.format
                    patchSettings({
                      format,
                      maxWords: format === 'shorts' ? 3 : 0,
                    })
                  }}
                  options={[
                    { value: 'shorts', label: 'Shorts (vertical)' },
                    { value: 'long', label: 'Vídeo longo (horizontal)' },
                  ]}
                />
              </div>

              <label className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Idioma</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition placeholder:text-text-muted focus:border-white/30"
                  onChange={(event) => patchSettings({ language: event.target.value || 'pt' })}
                  placeholder="pt"
                  value={settings.language}
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Beam size</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition focus:border-white/30"
                  min={1}
                  onChange={(event) => patchSettings({ beamSize: Number(event.target.value) || 1 })}
                  type="number"
                  value={settings.beamSize}
                />
              </label>

              <label className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Largura máx.</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition focus:border-white/30"
                  min={10}
                  onChange={(event) => patchSettings({ maxWidth: Number(event.target.value) || 42 })}
                  type="number"
                  value={settings.maxWidth}
                />
              </label>

              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm font-medium text-text-secondary">Saída customizada (.srt)</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 font-mono text-sm text-text-primary outline-none transition placeholder:text-text-muted focus:border-white/30"
                  onChange={(event) => setOutputPath(event.target.value.trim() || null)}
                  placeholder="Opcional: D:\Projetos\saida\episodio-01.srt"
                  value={settings.outputPath ?? ''}
                />
              </label>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              {/* Toggles que ajustam pos-processamento do texto antes de gravar o .srt. */}
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span>Uppercase</span>
                <Toggle
                  checked={settings.uppercase}
                  onChange={(checked) =>
                    patchSettings({
                      uppercase: checked,
                      lowercase: checked ? false : settings.lowercase,
                    })
                  }
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span>Lowercase</span>
                <Toggle
                  checked={settings.lowercase}
                  onChange={(checked) =>
                    patchSettings({
                      lowercase: checked,
                      uppercase: checked ? false : settings.uppercase,
                    })
                  }
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span>Remover acentos</span>
                <Toggle
                  checked={settings.noAccents}
                  onChange={(checked) => patchSettings({ noAccents: checked })}
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span>Remover pontuação</span>
                <Toggle
                  checked={settings.noPunctuation}
                  onChange={(checked) => patchSettings({ noPunctuation: checked })}
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span>Forçar CPU</span>
                <Toggle
                  checked={settings.useCpu}
                  onChange={(checked) => patchSettings({ useCpu: checked })}
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span className="space-y-0.5">
                  <span className="block">Gerar .srt em inglês também</span>
                  <span className="block text-xs text-text-muted">Opcional — os botões de queima já traduzem sozinhos</span>
                </span>
                <Toggle
                  checked={settings.translateTo.includes('en')}
                  onChange={(checked) =>
                    patchSettings({
                      translateTo: checked
                        ? [...settings.translateTo, 'en']
                        : settings.translateTo.filter((lang) => lang !== 'en'),
                    })
                  }
                />
              </div>
              <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span className="space-y-0.5">
                  <span className="block">Gerar .srt em chinês também</span>
                  <span className="block text-xs text-text-muted">Opcional — os botões de queima já traduzem sozinhos</span>
                </span>
                <Toggle
                  checked={settings.translateTo.includes('zh')}
                  onChange={(checked) =>
                    patchSettings({
                      translateTo: checked
                        ? [...settings.translateTo, 'zh']
                        : settings.translateTo.filter((lang) => lang !== 'zh'),
                    })
                  }
                />
              </div>
              <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span className="block text-xs uppercase tracking-[0.18em] text-text-muted">Tipo de vídeo</span>
                <span className="block text-xs text-text-muted">Ajusta o tom da tradução em chinês (vale pra queima também)</span>
                <input
                  className="w-full bg-transparent text-text-primary outline-none placeholder:text-text-muted"
                  onChange={(event) => patchSettings({ videoType: event.target.value })}
                  placeholder="ex.: gameplay de terror, corte engraçado, reação"
                  type="text"
                  value={settings.videoType}
                />
              </div>
              <div className="space-y-2 rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
                <span className="block text-xs uppercase tracking-[0.18em] text-text-muted">Máx. palavras</span>
                <input
                  className="w-full bg-transparent text-text-primary outline-none"
                  min={0}
                  onChange={(event) => patchSettings({ maxWords: Math.max(0, Number(event.target.value) || 0) })}
                  type="number"
                  value={settings.maxWords}
                />
              </div>
            </div>
          </Card>

          <Card className="space-y-4">
            {/* Card explicativo para lembrar como o fluxo backend trabalha hoje. */}
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/8 text-white">
                <SlidersHorizontal className="h-5 w-5" />
              </div>
              <div>
                <h4 className="text-lg font-medium text-text-primary">Observações do fluxo</h4>
                <p className="text-sm text-text-secondary">O backend faz fila sequencial e acompanha logs do Python.</p>
              </div>
            </div>

            <div className="divide-y divide-white/6 rounded-xl border border-white/8 bg-black/20">
              {/* Cada linha descreve uma regra operacional importante do pipeline. */}
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">1 job de GPU por vez</p>
                <p>Transcrição, queima e Pré-Editor dividem a mesma fila pra não disputar VRAM.</p>
              </div>
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Output padrão inteligente</p>
                <p>Sem caminho customizado, o `.srt` sai ao lado do arquivo original.</p>
              </div>
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Compatível com o projeto Python local</p>
                <p>Procura `D:\Projetos\subtitle-forge` e ambientes virtuais comuns antes do fallback para `python`.</p>
              </div>
            </div>

            <div className="flex flex-wrap gap-3">
              {/* Atalhos para abrir o seletor nativo e alimentar a fila. */}
              <Button leadingIcon={<HardDriveDownload className="h-4 w-4" />} onClick={() => void onPickFiles()}>
                Adicionar à fila
              </Button>
              <Button leadingIcon={<Layers3 className="h-4 w-4" />} onClick={() => void onPickFiles()} variant="ghost">
                Batch manual
              </Button>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
