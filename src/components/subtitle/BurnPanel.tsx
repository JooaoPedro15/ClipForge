import { Flame, FolderSearch, Languages } from 'lucide-react'

import { Button } from '@/components/ui/Button'
import { TaskStatusIcon } from '@/components/ui/TaskStatusIcon'
import { formatLanguage } from '@/lib/utils'
import type { HardsubJobState, HardsubMode, SubtitleTask } from '@/types/subtitle'

interface BurnPanelProps {
  task: SubtitleTask
  onBurn: (taskId: string, mode: HardsubMode) => void
  onOpenOutput: (outputPath: string | null) => void
}

function isRunning(job: HardsubJobState | undefined): boolean {
  return Boolean(job && job.status !== 'completed' && job.status !== 'error' && job.status !== 'cancelled')
}

// Proximo passo de uma legenda pronta: queimar no video (traduzindo o que faltar).
export function BurnPanel({ task, onBurn, onOpenOutput }: BurnPanelProps) {
  const modes: Array<{ mode: HardsubMode; label: string }> = [
    { mode: 'zh', label: 'Só chinês' },
    { mode: 'zh-en', label: 'Chinês + inglês' },
    { mode: 'zh-original', label: `Chinês + ${formatLanguage(task.detectedLanguage ?? task.language)}` },
    // Nao queima: ignora o .zh.srt atual (que pode ter correcao manual) e gera outro pra revisar.
    { mode: 'translate-zh', label: 'Tradução nova (chinês)' },
  ]
  const jobs = modes.filter(({ mode }) => task.hardsubJobs[mode])

  return (
    <div className="mt-3 space-y-2 rounded-md border border-line bg-app p-3">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="mr-1 inline-flex items-center gap-1.5 text-xs text-text-secondary">
          <Flame className="h-3.5 w-3.5" />
          Queimar no vídeo
        </span>
        {modes.slice(0, 3).map(({ mode, label }) => (
          <Button disabled={isRunning(task.hardsubJobs[mode])} key={mode} onClick={() => onBurn(task.id, mode)} size="sm" variant="ghost">
            {label}
          </Button>
        ))}
        <Button
          disabled={isRunning(task.hardsubJobs['translate-zh'])}
          leadingIcon={<Languages className="h-3.5 w-3.5" />}
          onClick={() => onBurn(task.id, 'translate-zh')}
          size="sm"
          title="Ignora o .zh.srt atual e gera outro, sem queimar, pra revisar antes"
          variant="quiet"
        >
          Traduzir de novo
        </Button>
      </div>
      <p className="text-xs text-text-muted">A queima traduz sozinha o que faltar. O vídeo sai ao lado do original.</p>

      {jobs.length > 0 ? (
        <ul className="space-y-1.5 border-t border-line pt-2">
          {jobs.map(({ mode, label }) => {
            const job = task.hardsubJobs[mode] as HardsubJobState
            const done = job.status === 'completed'
            return (
              <li className="flex items-start gap-2 text-xs" key={mode}>
                <TaskStatusIcon progress={job.progress} status={job.status} />
                <div className="min-w-0 flex-1">
                  <p className="text-text-primary">
                    {label}
                    <span className="ml-2 text-text-secondary">
                      {done && mode === 'translate-zh'
                        ? 'pronta. Confira o .zh.srt e clique em "Só chinês" pra queimar.'
                        : done
                          ? 'pronto.'
                          : job.status === 'error'
                            ? ''
                            : job.message}
                    </span>
                  </p>
                  {job.status === 'error' ? (
                    <p className="mt-0.5 whitespace-pre-line text-status-warn">
                      {job.error}
                      {mode === 'translate-zh' ? '\nO .zh.srt anterior continua intacto.' : ''}
                    </p>
                  ) : null}
                </div>
                {done && job.outputPath ? (
                  <Button
                    leadingIcon={<FolderSearch className="h-3.5 w-3.5" />}
                    onClick={() => onOpenOutput(job.outputPath)}
                    size="sm"
                    variant="quiet"
                  >
                    {mode === 'translate-zh' ? 'Mostrar .zh.srt' : 'Mostrar vídeo'}
                  </Button>
                ) : null}
              </li>
            )
          })}
        </ul>
      ) : null}
    </div>
  )
}
