// ── Ícones usados na interface (lucide-react é a lib de ícones)
import { Film, FolderOutput, FolderSearch, Scissors, Waves } from 'lucide-react'
// ── Hooks do React: useMemo memoriza valores caros, useState gerencia estado local
import { useMemo, useState } from 'react'

// ── Componente que renderiza a lista de tarefas (jobs) do Pre-Editor
import { ClipSplitterTaskList } from '@/components/clipSplitter/TaskList'
// ── Componentes de UI reutilizáveis do design system do app
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { CustomSelect } from '@/components/ui/CustomSelect'
import { StatCard } from '@/components/ui/StatCard'
import { Toggle } from '@/components/ui/Toggle'
// ── Utilitário que extrai o nome do arquivo a partir de um caminho completo
import { getFileName } from '@/lib/utils'
// ── Store global do app (Zustand) — contém estado compartilhado entre páginas
import { useAppStore } from '@/store/appStore'

// ── Tipagem das props que o componente pai precisa fornecer (callbacks de ações)
interface ClipSplitterPageProps {
  /** Abre o file picker nativo para o usuário escolher a pasta de saída */
  onPickOutputDir: () => Promise<{ ok: boolean; message: string | null }>
  /** Abre o file picker nativo para o usuário escolher o vídeo fonte */
  onPickSourceFile: () => Promise<{ ok: boolean; message: string | null }>
  /** Dispara o processo de pre-edicao do bruto */
  onStartSplit: () => Promise<{ ok: boolean; message: string | null }>
  /** Cancela uma tarefa específica da fila, identificada pelo taskId */
  onCancelTask: (taskId: string) => void
  /** Abre a pasta de saída no explorador de arquivos do SO */
  onOpenOutput: (outputDir: string | null) => void
  /** Re-executa uma tarefa que falhou, usando o mesmo sourcePath */
  onRetryTask: (sourcePath: string) => void
}

/**
 * Página principal do Pre-Editor.
 * Permite selecionar um bruto longo e gerar uma pre-edicao unica com pausas mais limpas.
 */
export function ClipSplitterPage({
  onPickOutputDir,
  onPickSourceFile,
  onStartSplit,
  onCancelTask,
  onOpenOutput,
  onRetryTask,
}: ClipSplitterPageProps) {
  // ── Estado local: mensagem de feedback exibida após uma ação (ex: erro ou sucesso)
  const [actionMessage, setActionMessage] = useState<string | null>(null)

  // ── Leitura de fatias do estado global via Zustand (cada seletor isola re-renders)
  const sourcePath = useAppStore((state) => state.clipSplitterSourcePath) // caminho do vídeo selecionado
  const settings = useAppStore((state) => state.clipSplitterSettings) // configurações de corte atuais
  const tasks = useAppStore((state) => state.clipSplitterTasks) // lista de tarefas (jobs) criados
  const patchSettings = useAppStore((state) => state.patchClipSplitterSettings) // fn para atualizar settings parcialmente
  const setOutputDir = useAppStore((state) => state.setClipSplitterOutputDir) // fn para definir pasta de saída

  // ── Deriva o nome curto do arquivo (ex: "video.mp4") ou mensagem padrão
  const sourceName = sourcePath ? getFileName(sourcePath) : 'Nenhum video selecionado'

  // ── Filtra tarefas por status para exibir contadores e alertas
  const completedTasks = tasks.filter((task) => task.status === 'completed')
  const activeTasks = tasks.filter(
    (task) => task.status === 'queued' || task.status === 'preparing' || task.status === 'processing',
  )

  // ── Soma total de arquivos limpos gerados por todas as tarefas concluídas nesta sessão
  const exportedClips = completedTasks.reduce((total, task) => total + task.clipsCreated, 0)

  // ── Pega a pasta de saída mais recente: primeiro das tasks, depois do settings, senão null
  const latestOutputDir = tasks.find((task) => task.outputDir)?.outputDir ?? settings.outputDir ?? null

  // ── Texto descritivo que muda conforme o modo selecionado (memorizado para evitar recálculo)
  const modeDescription = useMemo(() => {
    if (settings.mode === 'fixed') {
      return 'Mantem o bruto em um arquivo unico, sem dividir em partes curtas.'
    }

    return 'Analisa pausas e comprime silencios mantendo o video inteiro em ordem.'
  }, [settings.mode])

  /**
   * Wrapper genérico para executar uma ação assíncrona (pick file, start split, etc.)
   * e atualizar a mensagem de feedback na UI com o resultado.
   */
  async function runAction(action: () => Promise<{ ok: boolean; message: string | null }>) {
    const result = await action()
    setActionMessage(result.message)
  }

  // ── Início do JSX — layout principal da página ─────────────────────────────
  return (
    <div className="space-y-6">
      {/* ── Linha de stat cards no topo: fonte, clips exportados, fila ──────── */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Card que mostra o status do vídeo fonte selecionado */}
        <StatCard
          hint={sourcePath ? sourceName : 'Escolha o bruto principal para ativar a exportacao.'}
          icon={<Film className="h-4 w-4" />}
          label="Fonte atual"
          value={sourcePath ? 'Video carregado' : 'Aguardando'}
        />
        {/* Card que mostra quantos clips já foram exportados nesta sessão */}
        <StatCard
          hint="Soma dos videos limpos entregues pelos jobs concluidos nesta sessao."
          icon={<Scissors className="h-4 w-4" />}
          label="Videos limpos"
          value={String(exportedClips)}
        />
        {/* Card que mostra se há jobs na fila ou se está livre */}
        <StatCard
          hint={activeTasks.length > 0 ? 'Existe job rodando ou aguardando na fila.' : 'Fila livre para nova pre-edicao.'}
          icon={<FolderOutput className="h-4 w-4" />}
          label="Fila"
          value={activeTasks.length > 0 ? `${activeTasks.length} ativo(s)` : 'Livre'}
        />
      </div>

      {/* ── Grid principal: coluna esquerda (entrada + tasks) | coluna direita (config) */}
      <div className="grid gap-6 xl:grid-cols-[1.3fr_0.95fr]">
        {/* ════════ COLUNA ESQUERDA ════════ */}
        <div className="space-y-6">
          {/* ── Card de entrada: seleção de vídeo e ações principais ────────── */}
          <Card className="space-y-5">
            {/* Cabeçalho do card com título, descrição e badge do modo ativo */}
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <h3 className="text-2xl font-semibold text-text-primary">Vídeo base para pré-edição</h3>
                <p className="mt-2 max-w-2xl text-sm leading-7 text-text-secondary">
                  Escolha um video longo, ajuste a reducao de pausas e gere uma versao unica mais rapida de revisar.
                </p>
              </div>
              {/* Badge colorido indica o modo atual: IA (verde), Silêncio (azul) ou Fixo (amarelo) */}
              <Badge tone={settings.mode === 'silence' ? 'blue' : 'yellow'}>
                {settings.mode === 'silence' ? 'Pre-edicao' : 'Fixo'}
              </Badge>
            </div>

            {/* ── Box com o nome e caminho completo do arquivo selecionado ──── */}
            <div className="rounded-2xl border border-white/8 bg-black/16 p-5">
              <p className="text-sm font-medium text-text-secondary">Arquivo selecionado</p>
              <p className="mt-3 text-lg font-medium text-text-primary">{sourceName}</p>
              <p className="mt-2 break-all font-mono text-xs text-text-muted">{sourcePath ?? 'Nenhum caminho carregado.'}</p>
            </div>

            {/* ── Botões de ação: selecionar vídeo, escolher pasta, exportar, abrir saída */}
            <div className="flex flex-wrap gap-3">
              {/* Abre o file picker para selecionar o vídeo fonte */}
              <Button onClick={() => void runAction(onPickSourceFile)}>Selecionar video</Button>
              {/* Abre o file picker para escolher a pasta de saida da pre-edicao */}
              <Button onClick={() => void runAction(onPickOutputDir)} variant="ghost">
                Escolher pasta de saida
              </Button>
              {/* Inicia o processo de exportacao da pre-edicao */}
              <Button onClick={() => void runAction(onStartSplit)} variant="ghost">
                Gerar pre-edicao
              </Button>
              {/* Só aparece se já existe uma pasta de saída — abre no explorador do SO */}
              {latestOutputDir ? (
                <Button leadingIcon={<FolderSearch className="h-4 w-4" />} onClick={() => onOpenOutput(latestOutputDir)} variant="ghost">
                  Abrir saida
                </Button>
              ) : null}
            </div>

            {/* ── Mensagem de feedback (erro/sucesso) exibida após uma ação ── */}
            {actionMessage ? <p className="text-sm text-amber-300">{actionMessage}</p> : null}
          </Card>

          {/* ── Lista de tarefas (jobs) — mostra progresso, status, ações de cada task */}
          <ClipSplitterTaskList
            onCancel={onCancelTask}
            onOpenOutput={onOpenOutput}
            onRetry={onRetryTask}
            tasks={tasks}
          />
        </div>

        {/* ════════ COLUNA DIREITA ════════ */}
        <div className="space-y-6">
          {/* ── Card de configuração de corte ──────────────────────────────── */}
          <Card className="space-y-5">
            <div>
              <h3 className="text-xl font-semibold text-text-primary">Configuração de pausas</h3>
              <p className="mt-1 text-sm text-text-secondary">Regras usadas na próxima pré-edição.</p>
            </div>

            {/* ── Seletor de modo: "Silêncio + alvo de duração" ou "Duração fixa" */}
            <div className="space-y-2">
              <span className="text-sm font-medium text-text-secondary">Modo</span>
              <CustomSelect
                value={settings.mode}
                onChange={(value) => patchSettings({ mode: value as typeof settings.mode })}
                options={[
                  { value: 'silence', label: 'Silencio + alvo de duracao' },
                  { value: 'fixed', label: 'Duracao fixa' },
                ]}
              />
              {/* Texto explicativo que muda dinamicamente conforme o modo selecionado */}
              <p className="text-sm leading-6 text-text-secondary">{modeDescription}</p>
            </div>

            {/* ── Campos numéricos de configuração (grid 2 colunas) ─────────── */}
            <div className="space-y-2">
              <span className="text-sm font-medium text-text-secondary">Intensidade</span>
              <CustomSelect
                value={settings.preEditMode}
                onChange={(value) => patchSettings({ preEditMode: value as typeof settings.preEditMode })}
                options={[
                  { value: 'conservative', label: 'Conservative' },
                  { value: 'balanced', label: 'Balanced' },
                  { value: 'aggressive', label: 'Aggressive' },
                ]}
              />
            </div>

            <div className="flex items-center justify-between rounded-xl border border-white/8 bg-white/[0.03] px-4 py-3 text-sm text-text-secondary">
              <span>Salvar JSON de debug</span>
              <Toggle checked={settings.writeDebugJson} onChange={(checked) => patchSettings({ writeDebugJson: checked })} />
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm font-medium text-text-secondary">Faixa de voz (0:a:N)</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition focus:border-white/30"
                  onChange={(event) => patchSettings({ analysisAudioTrack: event.target.value.trim() || '1' })}
                  placeholder="1 ou mic"
                  value={settings.analysisAudioTrack}
                />
              </label>
              {/* Duração mínima de silêncio para ser considerado pausa (modo silêncio) */}
              <label className="space-y-2">
                <span className="text-sm font-medium text-text-secondary">Silencio min. (s)</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition focus:border-white/30"
                  min={0.1}
                  onChange={(event) => patchSettings({ silenceMinDurationSec: Number(event.target.value) || 0.1 })}
                  step="0.05"
                  type="number"
                  value={settings.silenceMinDurationSec}
                />
              </label>

              {/* Threshold em dB abaixo do qual o áudio é considerado silêncio (ocupa 2 colunas) */}
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm font-medium text-text-secondary">Threshold de silencio (dB)</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 text-text-primary outline-none transition focus:border-white/30"
                  max={-5}
                  min={-90}
                  onChange={(event) => patchSettings({ silenceThresholdDb: Number(event.target.value) || -35 })}
                  type="number"
                  value={settings.silenceThresholdDb}
                />
              </label>

              {/* Campo de texto para pasta de saída customizada (opcional, ocupa 2 colunas) */}
              <label className="space-y-2 sm:col-span-2">
                <span className="text-sm font-medium text-text-secondary">Pasta de saida</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-black/16 px-4 py-3 font-mono text-sm text-text-primary outline-none transition placeholder:text-text-muted focus:border-white/30"
                  onChange={(event) => setOutputDir(event.target.value.trim() || null)}
                  placeholder="Opcional: D:\\Projetos\\preedits\\episodio-01"
                  value={settings.outputDir ?? ''}
                />
              </label>
            </div>

            <p className="text-xs leading-6 text-text-muted">
              A intensidade controla quanto cada pausa sera comprimida. O modo balanced e o padrao para preservar respiro
              sem deixar o bruto lento.
            </p>

            <div className="rounded-xl border border-white/8 bg-black/16 px-4 py-4 text-sm leading-6 text-text-secondary">
              O resultado final continua sendo um video longo em ordem original. Use o JSON de debug quando quiser auditar
              quais pausas foram comprimidas.
            </div>
          </Card>

          {/* ── Card informativo: explica como o motor de pre-edicao funciona ──── */}
          <Card className="space-y-4">
            {/* Cabeçalho com ícone e descrição geral */}
            <div className="flex items-center gap-3">
              <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/8 text-white">
                <Waves className="h-5 w-5" />
              </div>
              <div>
                <p className="text-lg font-medium text-text-primary">Como esse motor trabalha</p>
                <p className="text-sm text-text-secondary">
                  Exporta um video limpo unico e depende de FFmpeg/FFprobe disponiveis na maquina.
                </p>
              </div>
            </div>

            {/* ── Blocos explicativos de cada modo/funcionalidade ────────────── */}
            <div className="divide-y divide-white/6 rounded-xl border border-white/8 bg-black/20">
              {/* Explica o modo fixo */}
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Modo fixo</p>
                <p>Mantem o bruto em um arquivo unico, sem dividir automaticamente em partes curtas.</p>
              </div>
              {/* Explica o modo silêncio */}
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Modo silencio</p>
                <p>Classifica pausas e comprime silencios sem quebrar a ordem original do video.</p>
              </div>
              {/* Explica o contexto transcrito */}
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Contexto transcrito</p>
                <p>Usa a transcricao para evitar cortes secos depois de conectores como "que", "mas" e "pra".</p>
              </div>
              {/* Explica o comportamento padrão da pasta de saída */}
              <div className="px-4 py-3.5 text-sm leading-6 text-text-secondary">
                <p className="font-medium text-text-primary">Saida padrao</p>
                <p>Sem pasta customizada, o app cria uma pasta irma do arquivo com sufixo `_preedit`.</p>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
