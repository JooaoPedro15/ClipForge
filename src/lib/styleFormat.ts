// Apresentacao do aprendizado de estilo (puro, testavel sem React).
import { STYLE_MIN_VIDEOS, type StyleLibrary, type StyleProfileName, type StyleProfileParams } from '@/types/subtitleStyle'

export const PROFILE_LABELS: Record<StyleProfileName, string> = {
  vertical: 'Vertical (Shorts)',
  horizontal: 'Horizontal (vídeo longo)',
}

// Acerto de quebra (F1 de 0 a 1) como porcentagem.
export function formatF1(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '--'
  }
  return `${Math.round(value * 100)}%`
}

export interface ProfileStatus {
  videos: number
  remaining: number
  // A geracao so usa o perfil com modelo treinado e o minimo de videos.
  active: boolean
}

export function getProfileStatus(library: StyleLibrary | null, profile: StyleProfileName): ProfileStatus {
  const videos = library?.videos.filter((video) => video.profile === profile).length ?? 0
  const minVideos = library?.minVideos ?? STYLE_MIN_VIDEOS
  const hasModel = Boolean(library?.profiles[profile])
  return { videos, remaining: Math.max(0, minVideos - videos), active: hasModel && videos >= minVideos }
}

export function describeTiming(params: StyleProfileParams): string {
  return [
    `Entra ${Math.round(params.lead_in_ms)} ms antes da fala`,
    `segura ${Math.round(params.hold_ms)} ms depois`,
    `cola buracos de até ${Math.round(params.glue_ms)} ms`,
    `${params.min_words} a ${params.max_words} palavras`,
  ].join(' · ')
}
