import { Check, FolderOpen, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { InspectorSection } from '@/components/inspector/InspectorSection'
import { StyleBatchReportBox, StyleProfile, StyleReportBox } from '@/components/subtitle/StyleProfile'
import { Button } from '@/components/ui/Button'
import { CustomSelect } from '@/components/ui/CustomSelect'
import { useSubtitleStyle } from '@/hooks/useSubtitleStyle'
import { getProfileStatus } from '@/lib/styleFormat'
import { cn, getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'
import type { StyleLibrary, StyleProfileName, StyleProjectScan, StyleProjectSequence } from '@/types/subtitleStyle'

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
// Com projeto do Premiere, bruto e final aceitam varios arquivos (cada um acha a sua sequencia).
const PICKERS: Array<{ kind: PickKind; label: string; hint: string; projectHint?: string }> = [
  {
    kind: 'original',
    label: 'Bruto legendado',
    hint: 'o vídeo ou mp3 que o app legendou',
    projectHint: 'um ou vários mp3 (Sequência 43.mp3 = Sequência 43)',
  },
  { kind: 'srt', label: 'Correções', hint: 'SRT ou projeto do Premiere (.prproj)' },
  {
    kind: 'final',
    label: 'Vídeo final',
    hint: 'já com os seus cortes',
    projectHint: 'opcional: o projeto já diz; escolha vários se faltar',
  },
]

function isPremiereProject(filePath: string | null) {
  return Boolean(filePath?.toLowerCase().endsWith('.prproj'))
}

function isTaught(item: StyleProjectSequence, library: StyleLibrary | null) {
  return Boolean(item.originalPath && library?.videos.some((video) => video.originalPath === item.originalPath))
}

// Sem final no projeto, os videos escolhidos sao transcritos e casados pelo que se fala neles.
function finalHint(item: StyleProjectSequence, hasChosenFinals: boolean) {
  if (item.finalPath) {
    return null
  }
  return hasChosenFinals ? 'final pelo conteúdo dos vídeos' : 'escolha o vídeo final'
}

function sequenceHint(item: StyleProjectSequence, library: StyleLibrary | null, hasChosenFinals: boolean) {
  return [
    `${item.cards} legendas`,
    isTaught(item, library) ? 'já ensinada' : null,
    item.originalPath ? null : 'bruto não achado',
    finalHint(item, hasChosenFinals),
  ]
    .filter(Boolean)
    .join(' · ')
}

function describeChosen(files: string[]) {
  const first = files[0]
  if (!first) {
    return null
  }
  return files.length === 1 ? getFileName(first) : `${files.length} arquivos (${getFileName(first)}, …)`
}

// Secao "Meu estilo" do Inspetor: ensina o app com um video que o usuario corrigiu no Premiere.
export function StylePanel() {
  const style = useSubtitleStyle()
  const settings = useAppStore((state) => state.subtitleSettings)
  // Tudo que o usuario escolheu em cada campo: com SRT vale o primeiro; com projeto, a lista inteira.
  const [chosen, setChosen] = useState<Record<PickKind, string[]>>({ original: [], srt: [], final: [] })
  const [project, setProject] = useState<StyleProjectScan | null>(null)
  const [sequence, setSequence] = useState<string | null>(null)
  const [originalsDir, setOriginalsDir] = useState<string | null>(null)

  if (!style.available) {
    return null
  }

  const projectPath = chosen.srt[0] ?? null
  const projectMode = isPremiereProject(projectPath)
  const originals = (files: string[], folder: string | null) => [...files, ...(folder ? [folder] : [])]

  async function pick(kind: PickKind) {
    const selected = await window.clipforge.dialog.openFiles(PICK_FILTERS[kind])
    if (selected.length === 0) {
      return
    }
    setChosen((current) => ({ ...current, [kind]: selected }))
    if (kind === 'srt') {
      const first = selected[0] ?? null
      setSequence(null)
      setProject(isPremiereProject(first) && first ? await style.scanProject(first, originals(chosen.original, originalsDir)) : null)
    } else if (kind === 'original' && projectMode && projectPath) {
      // Brutos novos: rele o projeto pra mostrar quais sequencias agora tem bruto.
      setProject(await style.scanProject(projectPath, originals(selected, originalsDir)))
    }
  }

  // Pasta dos brutos: Sequencia 43.mp3 casa com a sequencia de mesmo nome.
  async function pickOriginalsDir() {
    const folder = await window.clipforge.dialog.openDirectory()
    if (!folder || !projectPath) {
      return
    }
    setOriginalsDir(folder)
    setProject(await style.scanProject(projectPath, originals(chosen.original, folder)))
  }

  async function teachProject(only: string | null) {
    if (!projectPath) {
      return
    }
    await style.learnProject({
      projectPath,
      originals: originals(chosen.original, originalsDir),
      finals: chosen.final,
      only,
      model: settings.model,
      language: settings.language,
      useCpu: settings.useCpu,
    })
  }

  async function teach() {
    if (projectMode) {
      await teachProject(sequence)
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
  const ready = !busy && (projectMode ? Boolean(sequence) : chosen.original.length > 0 && chosen.srt.length > 0 && chosen.final.length > 0)
  // Com bruto e com final (do projeto ou pra casar pelo conteudo), ainda nao ensinadas: o que o "Ensinar todas" tenta.
  const pending =
    projectMode && project
      ? project.sequences.filter((item) => item.originalPath && (item.finalPath || chosen.final.length > 0) && !isTaught(item, style.library))
      : []
  const selectedSequence = project?.sequences.find((item) => item.name === sequence) ?? null
  const activeProfiles = PROFILES.filter((profile) => getProfileStatus(style.library, profile).active)
  const summary =
    activeProfiles.length === 0 ? 'Nenhum perfil ativo' : activeProfiles.length === 1 ? '1 perfil ativo' : '2 perfis ativos'

  return (
    <InspectorSection summary={summary} title="Meu estilo">
      <p className="text-xs leading-snug text-text-muted">
        Ensine com um vídeo que você corrigiu no Premiere: o SRT ou o próprio projeto, com a legenda já em gráfico.
      </p>

      <ol className="space-y-1.5">
        {PICKERS.map((picker, index) => {
          const files = chosen[picker.kind]
          const label = picker.kind === 'srt' ? describeChosen(files.slice(0, 1)) : projectMode ? describeChosen(files) : describeChosen(files.slice(0, 1))
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
                    label ? 'bg-text-primary text-black' : 'border border-line-strong text-text-muted',
                  )}
                >
                  {label ? <Check className="h-3 w-3" /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-text-primary">{picker.label}</span>
                  <span className={cn('block truncate text-xs', label ? 'font-mono text-text-secondary' : 'text-text-muted')}>
                    {label ?? (projectMode && picker.projectHint ? picker.projectHint : picker.hint)}
                  </span>
                </span>
              </button>
              {picker.kind === 'srt' && style.scanning ? (
                <p className="mt-1.5 flex items-center gap-2 text-xs text-text-secondary">
                  <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  Lendo o projeto…
                </p>
              ) : null}
              {picker.kind === 'srt' && projectMode && project ? (
                <>
                  <CustomSelect
                    className="mt-1.5"
                    onChange={setSequence}
                    options={project.sequences.map((item) => ({
                      value: item.name,
                      label: item.name,
                      hint: sequenceHint(item, style.library, chosen.final.length > 0),
                    }))}
                    placeholder="Escolha a sequência (ou use Ensinar todas)"
                    value={sequence ?? ''}
                  />
                  {selectedSequence ? (
                    <p className="mt-1 truncate px-1 text-xs text-text-muted">
                      Bruto: {selectedSequence.originalPath ? getFileName(selectedSequence.originalPath) : 'não achado'} · Final:{' '}
                      {selectedSequence.finalPath
                        ? getFileName(selectedSequence.finalPath)
                        : chosen.final.length > 0
                          ? 'pelo conteúdo'
                          : 'não achado'}
                    </p>
                  ) : null}
                  <button
                    className="app-no-drag mt-1.5 flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-xs text-text-secondary transition-colors hover:text-text-primary"
                    onClick={() => void pickOriginalsDir()}
                    type="button"
                  >
                    <FolderOpen className="h-3.5 w-3.5 shrink-0" />
                    <span className="truncate">
                      {originalsDir ? `Brutos de ${getFileName(originalsDir)}` : 'Pasta dos brutos (Sequência 43.mp3 = Sequência 43)'}
                    </span>
                  </button>
                </>
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
        {style.running ? 'Ensinando…' : projectMode && sequence ? `Ensinar ${sequence}` : 'Ensinar'}
      </Button>
      {projectMode && project ? (
        <Button className="w-full" disabled={pending.length === 0 || busy} onClick={() => void teachProject(null)} size="sm" variant="ghost">
          {pending.length === 0 ? 'Nada novo pra ensinar no projeto' : `Ensinar todas (${pending.length})`}
        </Button>
      ) : null}

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
