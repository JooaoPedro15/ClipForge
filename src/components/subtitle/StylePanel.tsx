import { Check, FolderOpen, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { InspectorSection } from '@/components/inspector/InspectorSection'
import { StyleBatchReportBox, StyleProfile, StyleReportBox } from '@/components/subtitle/StyleProfile'
import { Button } from '@/components/ui/Button'
import { useSubtitleStyle } from '@/hooks/useSubtitleStyle'
import { getProfileStatus } from '@/lib/styleFormat'
import { cn, getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type { StyleProfileName, StyleProjectScan } from '@/types/subtitleStyle'

type PickKind = 'original' | 'srt' | 'final'

const VIDEO_EXTENSIONS = ['mp4', 'mov', 'mkv', 'avi', 'webm']
const PICK_FILTERS: Record<PickKind, Array<{ name: string; extensions: string[] }>> = {
  // O bruto pode ser o mp3 da sequencia: e ele que o usuario manda o app legendar.
  original: [{ name: 'Vídeo ou áudio', extensions: [...VIDEO_EXTENSIONS, 'mp3', 'wav', 'm4a'] }],
  srt: [{ name: 'SRT ou projeto do Premiere', extensions: ['srt', 'prproj'] }],
  final: [{ name: 'Vídeo', extensions: VIDEO_EXTENSIONS }],
}
const PROFILES: StyleProfileName[] = ['vertical', 'horizontal']
// A ordem e a do fluxo real: legenda no app, corrige no Premiere, exporta o final.
// Com projeto do Premiere, bruto e final aceitam varios arquivos: cada bruto acha o seu Short no projeto.
const PICKERS: Array<{ kind: PickKind; label: string; hint: string; projectHint?: string }> = [
  {
    kind: 'original',
    label: 'Bruto legendado',
    hint: 'o vídeo ou mp3 que o app legendou',
    projectHint: 'opcional: sem escolher, usa os mp3 do lado dos SRT importados',
  },
  { kind: 'srt', label: 'Correções', hint: 'SRT ou projeto do Premiere (.prproj)' },
  {
    kind: 'final',
    label: 'Vídeo final',
    hint: 'já com os seus cortes',
    projectHint: 'o projeto só guarda a última exportação: escolha os outros (pode ser a pasta toda)',
  },
]

function isPremiereProject(filePath: string | null) {
  return Boolean(filePath?.toLowerCase().endsWith('.prproj'))
}

function describeChosen(files: string[]) {
  const first = files[0]
  if (!first) {
    return null
  }
  return files.length === 1 ? getFileName(first) : `${files.length} arquivos (${getFileName(first)}, …)`
}

// Secao "Meu estilo" do Inspetor: ensina o app com videos que o usuario corrigiu no Premiere.
export function StylePanel() {
  const style = useSubtitleStyle()
  const settings = useAppStore((state) => state.subtitleSettings)
  // Tudo que o usuario escolheu em cada campo: com SRT vale o primeiro; com projeto, a lista inteira.
  const [chosen, setChosen] = useState<Record<PickKind, string[]>>({ original: [], srt: [], final: [] })
  const [project, setProject] = useState<StyleProjectScan | null>(null)
  const [originalsDir, setOriginalsDir] = useState<string | null>(null)

  if (!style.available) {
    return null
  }

  const projectPath = chosen.srt[0] ?? null
  const projectMode = isPremiereProject(projectPath)
  const originals = (files: string[], folder: string | null) => [...files, ...(folder ? [folder] : [])]

  async function rescan(path: string, files: string[], folder: string | null) {
    setProject(await style.scanProject(path, originals(files, folder)))
  }

  async function pick(kind: PickKind) {
    const selected = await window.clipforge.dialog.openFiles(PICK_FILTERS[kind])
    if (selected.length === 0) {
      return
    }
    setChosen((current) => ({ ...current, [kind]: selected }))
    const first = selected[0] ?? null
    if (kind === 'srt') {
      if (isPremiereProject(first) && first) {
        await rescan(first, chosen.original, originalsDir)
      } else {
        setProject(null)
      }
    } else if (kind === 'original' && projectMode && projectPath) {
      await rescan(projectPath, selected, originalsDir)
    }
  }

  // Pasta dos brutos: todos os mp3 dela entram (cada um acha o seu Short no projeto).
  async function pickOriginalsDir() {
    const folder = await window.clipforge.dialog.openDirectory()
    if (!folder) {
      return
    }
    setOriginalsDir(folder)
    if (projectPath && projectMode) {
      await rescan(projectPath, chosen.original, folder)
    }
  }

  async function teach() {
    if (projectMode && projectPath) {
      await style.learnProject({
        projectPath,
        originals: originals(chosen.original, originalsDir),
        finals: chosen.final,
        model: settings.model,
        language: settings.language,
        useCpu: settings.useCpu,
      })
      return
    }
    const [originalPath] = chosen.original
    const [finalPath] = chosen.final
    if (!originalPath || !projectPath || !finalPath) {
      return
    }
    await style.learn({
      originalPath,
      srtPath: projectPath,
      finalPath,
      model: settings.model,
      language: settings.language,
      useCpu: settings.useCpu,
    })
  }

  const busy = style.running || style.scanning
  const rawCount = project?.rawFiles ?? 0
  const ready = !busy && (projectMode ? rawCount > 0 : chosen.original.length > 0 && chosen.srt.length > 0 && chosen.final.length > 0)
  const teachLabel = projectMode ? `Ensinar ${rawCount} ${rawCount === 1 ? 'bruto' : 'brutos'}` : 'Ensinar'
  const activeProfiles = PROFILES.filter((profile) => getProfileStatus(style.library, profile).active)
  const summary =
    activeProfiles.length === 0 ? 'Nenhum perfil ativo' : activeProfiles.length === 1 ? '1 perfil ativo' : '2 perfis ativos'

  return (
    <InspectorSection summary={summary} title="Meu estilo">
      <p className="text-xs leading-snug text-text-muted">
        Ensine com vídeos que você corrigiu no Premiere: o SRT ou o próprio projeto, com a legenda já em gráfico.
      </p>

      <ol className="space-y-1.5">
        {PICKERS.map((picker, index) => {
          const files = chosen[picker.kind]
          const label = describeChosen(projectMode && picker.kind !== 'srt' ? files : files.slice(0, 1))
          const folderLabel = picker.kind === 'original' && originalsDir ? `pasta ${getFileName(originalsDir)}` : null
          const shown = [label, projectMode ? folderLabel : null].filter(Boolean).join(' + ')
          return (
            <li key={picker.kind}>
              <button
                className="app-no-drag flex w-full items-center gap-3 rounded-md border border-line bg-raised px-3 py-2 text-left transition-colors hover:border-line-strong"
                onClick={() => void pick(picker.kind)}
                type="button"
              >
                <span
                  className={cn(
                    'flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-semibold',
                    shown ? 'bg-text-primary text-black' : 'border border-line-strong text-text-muted',
                  )}
                >
                  {shown ? <Check className="h-3 w-3" /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-text-primary">{picker.label}</span>
                  <span className={cn('block truncate text-xs', shown ? 'font-mono text-text-secondary' : 'text-text-muted')}>
                    {shown || (projectMode && picker.projectHint ? picker.projectHint : picker.hint)}
                  </span>
                </span>
              </button>
              {picker.kind === 'original' && projectMode ? (
                <button
                  className="app-no-drag mt-1 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-xs text-text-secondary transition-colors hover:text-text-primary"
                  onClick={() => void pickOriginalsDir()}
                  type="button"
                >
                  <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                  <span className="truncate">{originalsDir ? `Trocar a pasta dos brutos` : 'Usar uma pasta de brutos (ex.: audios legendas)'}</span>
                </button>
              ) : null}
              {picker.kind === 'srt' && style.scanning ? (
                <p className="mt-1.5 flex items-center gap-2 text-xs text-text-secondary">
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  Lendo o projeto…
                </p>
              ) : null}
              {picker.kind === 'srt' && projectMode && project && !style.scanning ? (
                <p className="mt-1 px-1 text-xs text-text-muted">
                  {project.sequences.length} {project.sequences.length === 1 ? 'sequência' : 'sequências'} com legenda em gráfico. Cada bruto
                  acha o seu Short pelo que é falado.
                </p>
              ) : null}
            </li>
          )
        })}
      </ol>

      <Button
        className="w-full"
        disabled={!ready}
        leadingIcon={style.running ? <LoaderCircle className="h-4 w-4 animate-spin" /> : null}
        onClick={() => void teach()}
        size="sm"
      >
        {style.running ? 'Ensinando…' : teachLabel}
      </Button>

      {style.running && style.progress ? <p className="text-xs text-text-secondary">{style.progress.message}</p> : null}
      {style.error ? (
        <p className="flex items-start gap-2 text-xs text-status-red">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {style.error}
        </p>
      ) : null}
      {style.report ? <StyleReportBox report={style.report} /> : null}
      {style.batchReport ? <StyleBatchReportBox report={style.batchReport} /> : null}

      {PROFILES.map((profile) => (
        <StyleProfile
          busy={style.running}
          key={profile}
          library={style.library}
          onForget={(videoId) => void style.forget(videoId)}
          profile={profile}
        />
      ))}
    </InspectorSection>
  )
}
