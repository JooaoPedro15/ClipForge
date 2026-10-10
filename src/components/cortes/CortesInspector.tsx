import { FileCode2 } from 'lucide-react'

import { FieldRow, ToggleField } from '@/components/inspector/fields'
import { InspectorSection } from '@/components/inspector/InspectorSection'
import { Button } from '@/components/ui/Button'
import { NumberStepper } from '@/components/ui/NumberStepper'
import { getFileName } from '@/lib/utils'
import { useAppStore } from '@/store/appStore'

interface CortesInspectorProps {
  onPickTemplate: () => void
}

// Inspetor dos Cortes: o molde do Premiere no topo e as regras da analise em secoes.
export function CortesInspector({ onPickTemplate }: CortesInspectorProps) {
  const settings = useAppStore((state) => state.cortesSettings)
  const patchSettings = useAppStore((state) => state.patchCortesSettings)
  const templateName = settings.templatePath ? getFileName(settings.templatePath) : null

  return (
    <div className="pb-6">
      <InspectorSection defaultOpen summary={templateName ?? 'nenhum'} title="Molde">
        <div className="flex items-center gap-2">
          <FileCode2 className="h-4 w-4 shrink-0 text-text-muted" />
          <span
            className={templateName ? 'min-w-0 flex-1 truncate font-mono text-xs text-text-primary' : 'min-w-0 flex-1 text-xs text-status-warn'}
            title={settings.templatePath || undefined}
          >
            {templateName ?? 'Nenhum molde escolhido'}
          </span>
          <Button onClick={onPickTemplate} size="sm" variant="ghost">
            {templateName ? 'Trocar' : 'Escolher XML'}
          </Button>
        </div>
        <p className="text-xs leading-snug text-text-muted">
          Uma sequência sua já montada (filme, webcam e loop), exportada em Arquivo › Exportar › Final Cut Pro XML. Vale pra todo react.
        </p>
      </InspectorSection>

      <InspectorSection summary={`filme ${settings.filmTrack}, mic ${settings.micTrack}`} title="Faixas de áudio">
        <FieldRow hint="Faixa com o som do filme" label="Filme">
          <NumberStepper label="faixa do filme" max={8} min={1} onChange={(filmTrack) => patchSettings({ filmTrack })} value={settings.filmTrack} />
        </FieldRow>
        <FieldRow hint="Faixa com a sua voz" label="Mic">
          <NumberStepper label="faixa do mic" max={8} min={1} onChange={(micTrack) => patchSettings({ micTrack })} value={settings.micTrack} />
        </FieldRow>
      </InspectorSection>

      <InspectorSection defaultOpen summary={`${settings.minSec}s / ${settings.targetSec}s / ${settings.maxSec}s`} title="Duração dos clipes">
        <FieldRow hint="Clipe nunca fica mais curto" label="Mínimo (s)">
          <NumberStepper
            label="duração mínima em segundos"
            max={settings.targetSec}
            min={10}
            onChange={(minSec) => patchSettings({ minSec })}
            step={5}
            value={settings.minSec}
          />
        </FieldRow>
        <FieldRow hint="O tamanho que o corte procura" label="Alvo (s)">
          <NumberStepper
            label="duração alvo em segundos"
            max={settings.maxSec}
            min={settings.minSec}
            onChange={(targetSec) => patchSettings({ targetSec })}
            step={5}
            value={settings.targetSec}
          />
        </FieldRow>
        <FieldRow hint="Clipe nunca passa disso" label="Máximo (s)">
          <NumberStepper
            label="duração máxima em segundos"
            max={900}
            min={settings.targetSec}
            onChange={(maxSec) => patchSettings({ maxSec })}
            step={5}
            value={settings.maxSec}
          />
        </FieldRow>
        <p className="text-xs leading-snug text-text-muted">Mudou depois de analisar? Use Refazer clipes no item: não lê o bruto de novo.</p>
      </InspectorSection>

      <InspectorSection summary={settings.titlesWithAi ? 'com IA' : 'numerados'} title="Títulos">
        <ToggleField
          checked={settings.titlesWithAi}
          hint="O qwen 7b local lê cada clipe e dá título e nota de gancho. Desligado: Clipe 01, 02... e nota só pela sua reação."
          label="Títulos com IA"
          onChange={(titlesWithAi) => patchSettings({ titlesWithAi })}
        />
      </InspectorSection>
    </div>
  )
}
