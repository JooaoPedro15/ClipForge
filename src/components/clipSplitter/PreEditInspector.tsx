import { PauseDiagram } from '@/components/clipSplitter/PauseDiagram'
import { FieldRow, inspectorInputClass, StackedField, ToggleField } from '@/components/inspector/fields'
import { InspectorSection } from '@/components/inspector/InspectorSection'
import { NumberStepper } from '@/components/ui/NumberStepper'
import { SegmentedControl } from '@/components/ui/SegmentedControl'
import { useAppStore } from '@/store/appStore'

const INTENSITY_HINTS = {
  conservative: 'Corta pouco. Bom pra conversa e história.',
  balanced: 'Tira o silêncio sem perder o respiro. Padrão.',
  aggressive: 'Ritmo de corte. Silêncio de 4s ou mais sai inteiro.',
} as const

// Inspetor do Pre-Editor: diagrama de pausas no topo e as regras da deteccao em secoes.
export function PreEditInspector() {
  const settings = useAppStore((state) => state.clipSplitterSettings)
  const patchSettings = useAppStore((state) => state.patchClipSplitterSettings)
  const compress = settings.mode === 'silence'

  return (
    <div className="pb-6">
      {/* A intensidade fica colada no diagrama porque e ela que muda a trilha de baixo. */}
      <div className="space-y-2 p-4">
        <PauseDiagram compress={compress} mode={settings.preEditMode} />
        <SegmentedControl
          label="Intensidade"
          onChange={(preEditMode) => patchSettings({ preEditMode, mode: 'silence' })}
          options={[
            { value: 'conservative', label: 'Leve' },
            { value: 'balanced', label: 'Equilibrada' },
            { value: 'aggressive', label: 'Forte' },
          ]}
          value={settings.preEditMode}
        />
        <p className="text-xs text-text-muted">
          {compress ? INTENSITY_HINTS[settings.preEditMode] : 'Pausas desligadas: o vídeo sai inteiro.'}
        </p>
      </div>

      <InspectorSection
        defaultOpen
        summary={`${settings.silenceThresholdDb} dB, ${settings.silenceMinDurationSec}s`}
        title="O que conta como pausa"
      >
        <FieldRow hint="Mais perto de 0 pega mais coisa como silêncio" label="Volume do silêncio (dB)">
          <NumberStepper
            label="volume do silêncio em dB"
            max={-5}
            min={-90}
            onChange={(silenceThresholdDb) => patchSettings({ silenceThresholdDb })}
            value={settings.silenceThresholdDb}
          />
        </FieldRow>
        <FieldRow hint="Pausa menor que isso fica intacta" label="Duração mínima (s)">
          <NumberStepper
            label="duração mínima da pausa em segundos"
            max={5}
            min={0.1}
            onChange={(silenceMinDurationSec) => patchSettings({ silenceMinDurationSec })}
            step={0.05}
            value={settings.silenceMinDurationSec}
          />
        </FieldRow>
      </InspectorSection>

      <InspectorSection summary={`faixa ${settings.analysisAudioTrack}${compress ? '' : ', sem cortes'}`} title="Avançado">
        <ToggleField
          checked={compress}
          hint="Desligado, só exporta o bruto inteiro"
          label="Encurtar pausas"
          onChange={(checked) => patchSettings({ mode: checked ? 'silence' : 'fixed' })}
        />
        <StackedField
          hint="Número da faixa (0 é a primeira) ou o nome dela, ex.: mic. A análise ouve só essa; o vídeo sai com todas."
          htmlFor="voice-track"
          label="Faixa de áudio da voz"
        >
          <input
            className={inspectorInputClass}
            id="voice-track"
            onChange={(event) => patchSettings({ analysisAudioTrack: event.target.value.trim() || '1' })}
            placeholder="1"
            value={settings.analysisAudioTrack}
          />
        </StackedField>
        <ToggleField
          checked={settings.writeDebugJson}
          hint="Lista cada pausa e quanto foi cortado"
          label="Salvar JSON de debug"
          onChange={(writeDebugJson) => patchSettings({ writeDebugJson })}
        />
      </InspectorSection>
    </div>
  )
}
