import { CaptionMonitor } from '@/components/subtitle/CaptionMonitor'
import { StylePanel } from '@/components/subtitle/StylePanel'
import { FieldRow, inspectorInputClass, StackedField, ToggleField } from '@/components/inspector/fields'
import { InspectorSection } from '@/components/inspector/InspectorSection'
import { CustomSelect } from '@/components/ui/CustomSelect'
import { NumberStepper } from '@/components/ui/NumberStepper'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAppStore } from '@/store/appStore'
import type { SubtitleModel } from '@/types/subtitle'

type LetterCase = 'normal' | 'upper' | 'lower'

const MODEL_OPTIONS: Array<{ value: SubtitleModel; label: string; hint: string }> = [
  { value: 'large-v3', label: 'large-v3', hint: 'Mais preciso. Padrão.' },
  { value: 'medium', label: 'medium', hint: 'Mais rápido, erra um pouco mais.' },
  { value: 'small', label: 'small', hint: 'Rápido, troca nomes próprios.' },
  { value: 'base', label: 'base', hint: 'Só pra teste.' },
  { value: 'tiny', label: 'tiny', hint: 'Só pra teste.' },
]

const LANGUAGE_OPTIONS = [
  { value: 'pt', label: 'Português' },
  { value: 'en', label: 'Inglês' },
  { value: 'es', label: 'Espanhol' },
  { value: 'de', label: 'Alemão' },
  { value: 'fr', label: 'Francês' },
  { value: 'it', label: 'Italiano' },
  { value: 'ja', label: 'Japonês' },
]

// Inspetor do SubtitleForge: previa no topo e as opcoes da transcricao em secoes.
export function SubtitleInspector() {
  const settings = useAppStore((state) => state.subtitleSettings)
  const patchSettings = useAppStore((state) => state.patchSubtitleSettings)
  const setOutputPath = useAppStore((state) => state.setSubtitleOutputPath)

  // Maiuscula e minuscula sao exclusivas: um controle so com 3 estados evita as duas ligadas.
  const letterCase: LetterCase = settings.uppercase ? 'upper' : settings.lowercase ? 'lower' : 'normal'
  const languageOptions = LANGUAGE_OPTIONS.some((option) => option.value === settings.language)
    ? LANGUAGE_OPTIONS
    : [...LANGUAGE_OPTIONS, { value: settings.language, label: settings.language }]
  const translations = settings.translateTo.map((lang) => `.${lang}.srt`).join(' e ')

  function toggleTranslation(lang: string, checked: boolean) {
    patchSettings({
      translateTo: checked ? [...settings.translateTo, lang] : settings.translateTo.filter((item) => item !== lang),
    })
  }

  return (
    <div className="pb-6">
      {/* O formato fica colado no monitor porque e ele que muda o quadro. */}
      <div className="space-y-2 p-4">
        <CaptionMonitor format={settings.format} options={settings} />
        <SegmentedControl
          label="Formato"
          onChange={(format) => patchSettings({ format, maxWords: format === 'shorts' ? 3 : 0 })}
          options={[
            { value: 'shorts', label: 'Shorts 9:16' },
            { value: 'long', label: 'Vídeo longo 16:9' },
          ]}
          value={settings.format}
        />
      </div>

      <InspectorSection defaultOpen title="Texto da legenda">
        <SegmentedControl
          label="Maiúsculas e minúsculas"
          onChange={(value) => patchSettings({ uppercase: value === 'upper', lowercase: value === 'lower' })}
          options={[
            { value: 'normal', label: 'Normal' },
            { value: 'upper', label: 'MAIÚSCULAS' },
            { value: 'lower', label: 'minúsculas' },
          ]}
          value={letterCase}
        />
        <ToggleField checked={settings.noAccents} label="Sem acentos" onChange={(noAccents) => patchSettings({ noAccents })} />
        <ToggleField
          checked={settings.noPunctuation}
          label="Sem pontuação"
          onChange={(noPunctuation) => patchSettings({ noPunctuation })}
        />
        <FieldRow hint="auto = segue as pausas da fala" label="Palavras por legenda">
          <NumberStepper
            label="palavras por legenda"
            max={12}
            min={0}
            onChange={(maxWords) => patchSettings({ maxWords })}
            value={settings.maxWords}
            zeroLabel="auto"
          />
        </FieldRow>
        <FieldRow label="Caracteres por linha">
          <NumberStepper
            label="caracteres por linha"
            max={80}
            min={10}
            onChange={(maxWidth) => patchSettings({ maxWidth })}
            value={settings.maxWidth}
          />
        </FieldRow>
        <ToggleField
          checked={settings.useStyle}
          hint="Vale quando o formato tem 3+ vídeos ensinados"
          label="Usar meu estilo"
          onChange={(useStyle) => patchSettings({ useStyle })}
        />
      </InspectorSection>

      <InspectorSection summary={settings.videoType || translations || 'Só na queima'} title="Tradução">
        <StackedField hint="Ajusta o tom da tradução em chinês, aqui e na queima." htmlFor="video-type" label="Tipo de vídeo">
          <input
            className={inspectorInputClass}
            id="video-type"
            onChange={(event) => patchSettings({ videoType: event.target.value })}
            placeholder="gameplay de terror, corte engraçado…"
            value={settings.videoType}
          />
        </StackedField>
        <p className="text-xs leading-snug text-text-muted">
          Os botões de queima já traduzem o que faltar. Marque só se quiser o .srt traduzido pra revisar antes.
        </p>
        <ToggleField
          checked={settings.translateTo.includes('en')}
          label="Gerar .en.srt junto"
          onChange={(checked) => toggleTranslation('en', checked)}
        />
        <ToggleField
          checked={settings.translateTo.includes('zh')}
          label="Gerar .zh.srt junto"
          onChange={(checked) => toggleTranslation('zh', checked)}
        />
      </InspectorSection>

      <StylePanel />

      <InspectorSection
        summary={`${settings.model}, ${settings.language}, ${settings.useCpu ? 'CPU' : 'GPU'}`}
        title="Avançado"
      >
        <StackedField htmlFor="whisper-model" label="Modelo do Whisper">
          <CustomSelect
            id="whisper-model"
            onChange={(model) => patchSettings({ model: model as SubtitleModel })}
            options={MODEL_OPTIONS}
            value={settings.model}
          />
        </StackedField>
        <StackedField htmlFor="whisper-language" label="Idioma falado">
          <CustomSelect
            id="whisper-language"
            onChange={(language) => patchSettings({ language })}
            options={languageOptions}
            value={settings.language}
          />
        </StackedField>
        <FieldRow hint="Maior = mais preciso e mais lento" label="Beam size">
          <NumberStepper
            label="beam size"
            max={10}
            min={1}
            onChange={(beamSize) => patchSettings({ beamSize })}
            value={settings.beamSize}
          />
        </FieldRow>
        <ToggleField
          checked={settings.useCpu}
          hint="Bem mais lento; use se a GPU estiver ocupada"
          label="Forçar CPU"
          onChange={(useCpu) => patchSettings({ useCpu })}
        />
        <StackedField hint="Vazio = .srt ao lado do vídeo." htmlFor="output-path" label="Salvar .srt em">
          <input
            className={`${inspectorInputClass} font-mono text-xs`}
            id="output-path"
            onChange={(event) => setOutputPath(event.target.value.trim() || null)}
            placeholder="D:\Projetos\saida\episodio-01.srt"
            value={settings.outputPath ?? ''}
          />
        </StackedField>
      </InspectorSection>
    </div>
  )
}
