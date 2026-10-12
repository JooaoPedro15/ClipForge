import { Check, LoaderCircle, TriangleAlert } from 'lucide-react'
import { useState } from 'react'

import { InspectorSection } from '@/components/inspector/InspectorSection'
import { StyleProfile, StyleReportBox } from '@/components/subtitle/StyleProfile'
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
const PICKERS: Array<{ kind: PickKind; label: string; hint: string }> = [
  { kind: 'original', label: 'Bruto legendado', hint: 'o vídeo ou mp3 que o app legendou' },
  { kind: 'srt', label: 'Correções', hint: 'SRT ou projeto do Premiere (.prproj)' },
  { kind: 'final', label: 'Vídeo final', hint: 'já com os seus cortes' },
]

function isPremiereProject(filePath: string | null) {
  return Boolean(filePath?.toLowerCase().endsWith('.prproj'))
}

function missingFilesHint(item: StyleProjectSequence) {
  if (!item.originalPath && !item.finalPath) {
    return 'escolha bruto e final'
  }
  if (!item.originalPath) {
    return 'escolha o bruto'
  }
  return item.finalPath ? null : 'escolha o final'
}

function sequenceHint(item: StyleProjectSequence, library: StyleLibrary | null) {
  const taught = Boolean(item.originalPath && library?.videos.some((video) => video.originalPath === item.originalPath))
  return [`${item.cards} legendas`, taught ? 'já ensinada' : null, missingFilesHint(item)].filter(Boolean).join(' · ')
}

// Secao "Meu estilo" do Inspetor: ensina o app com um video que o usuario corrigiu no Premiere.
export function StylePanel() {
  const style = useSubtitleStyle()
  const settings = useAppStore((state) => state.subtitleSettings)
  const [paths, setPaths] = useState<Record<PickKind, string | null>>({ original: null, srt: null, final: null })
  const [project, setProject] = useState<StyleProjectScan | null>(null)
  const [sequence, setSequence] = useState<string | null>(null)

  if (!style.available) {
    return null
  }

  const projectMode = isPremiereProject(paths.srt)

  async function pick(kind: PickKind) {
    const selected = await window.clipforge.dialog.openFiles(PICK_FILTERS[kind])
    const first = selected[0]
    if (!first) {
      return
    }
    setPaths((current) => ({ ...current, [kind]: first }))
    if (kind === 'srt') {
      setSequence(null)
      setProject(isPremiereProject(first) ? await style.scanProject(first) : null)
    }
  }

  // Trocar de sequencia troca bruto e final juntos: caminho velho de outra sequencia ensinaria errado.
  function chooseSequence(name: string) {
    const found = project?.sequences.find((item) => item.name === name)
    setSequence(name)
    if (found) {
      setPaths((current) => ({ ...current, original: found.originalPath, final: found.finalPath }))
    }
  }

  async function teach() {
    if (!paths.original || !paths.srt || !paths.final || (projectMode && !sequence)) {
      return
    }
    await style.learn({
      originalPath: paths.original,
      srtPath: paths.srt,
      sequence: projectMode ? sequence : null,
      finalPath: paths.final,
      model: settings.model,
      language: settings.language,
      useCpu: settings.useCpu,
    })
  }

  const ready =
    Boolean(paths.original && paths.srt && paths.final) && (!projectMode || Boolean(sequence)) && !style.running && !style.scanning
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
          const chosen = paths[picker.kind]
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
                    chosen ? 'bg-text-primary text-black' : 'border border-line-strong text-text-muted',
                  )}
                >
                  {chosen ? <Check className="h-3 w-3" /> : index + 1}
                </span>
                <span className="min-w-0">
                  <span className="block text-[13px] text-text-primary">{picker.label}</span>
                  <span className={cn('block truncate text-xs', chosen ? 'font-mono text-text-secondary' : 'text-text-muted')}>
                    {chosen ? getFileName(chosen) : picker.hint}
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
                <CustomSelect
                  className="mt-1.5"
                  onChange={chooseSequence}
                  options={project.sequences.map((item) => ({ value: item.name, label: item.name, hint: sequenceHint(item, style.library) }))}
                  placeholder="Escolha a sequência"
                  value={sequence ?? ''}
                />
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
        {style.running ? 'Ensinando…' : 'Ensinar'}
      </Button>

      {style.running && style.progress ? <p className="text-xs text-text-secondary">{style.progress.message}</p> : null}
      {style.error ? (
        <p className="flex items-start gap-2 text-xs text-status-red">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {style.error}
        </p>
      ) : null}
      {style.report ? <StyleReportBox report={style.report} /> : null}

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
