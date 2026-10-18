import type { Channel } from '@/lib/api'

/** Valeur d'un champ numérique : nombre côté API, chaîne pendant la saisie. */
type NumericInput = number | string

export interface ChannelSettingsForm {
  theme_category: string
  theme_prompt: string
  niche_prompt: string
  creative_brief: string
  youtube_category_id: string
  tone: string
  production_mode: string
  /** '' = hérite du défaut plateforme (data/agent_config.json → studio.animations). */
  animations: string
  /** '' = hérite du défaut plateforme (data/agent_config.json → studio.visual_style). */
  visual_style: string
  short_duration_s: NumericInput
  long_quota: NumericInput
  short_quota: NumericInput
  enabled_platforms: string[]
  tts_short_engine: string
  tts_short_voice: string
  ai_plan: string
  max_ai_images_per_video: NumericInput
}

export type UpdateChannelForm = (patch: Partial<ChannelSettingsForm>) => void

type Json = Record<string, unknown>

const DEFAULT_VOICE = 'fr-FR-Vivienne:DragonHDLatestNeural'

/** Clés de Channel.config qui ne sont plus lues par le backend : retirées à l'enregistrement. */
const LEGACY_CONFIG_KEYS = ['runway', 'media_validation', 'subtitles', 'engagement', 'media_library', 'quality']

function section(config: Json, key: string): Json {
  return (config[key] as Json) || {}
}

/** Profil voix des Shorts (le seul utilisé par Claude Studio), avec compat `gemini.apply_to`. */
function resolveShortTts(tts: Json): { engine: string; voice: string } {
  const shortRaw = tts.short as Json | undefined
  const gemini = section(tts, 'gemini')
  if (!shortRaw && (gemini.apply_to === 'shorts' || gemini.apply_to === 'both')) {
    return { engine: 'gemini', voice: String(gemini.voice || 'Puck') }
  }
  return {
    engine: String(shortRaw?.engine || tts.engine || 'azure'),
    voice: String(shortRaw?.voice || tts.voice || DEFAULT_VOICE),
  }
}

export function channelToFormState(channel: Channel): ChannelSettingsForm {
  const cfg = (channel.config || {}) as Json
  const pub = section(cfg, 'publishing')
  const prod = section(cfg, 'production')
  const ai = section(section(cfg, 'media_sources'), 'ai_fallback')
  const quotas = (pub.daily_quotas as Record<string, number>) || {}
  const shortTts = resolveShortTts(section(cfg, 'tts'))

  return {
    theme_category: channel.theme_category || '',
    theme_prompt: channel.theme_prompt || '',
    niche_prompt: channel.niche_prompt || '',
    creative_brief: channel.creative_brief || '',
    youtube_category_id: String(pub.youtube_category_id || '27'),
    tone: String(section(cfg, 'editorial').tone || ''),
    production_mode: String(prod.mode || 'mixed'),
    animations: String(section(cfg, 'studio').animations || ''),
    visual_style: String(section(cfg, 'studio').visual_style || ''),
    short_duration_s: Number(prod.short_duration_s || 60),
    long_quota: quotas.long ?? 1,
    short_quota: quotas.short ?? 3,
    enabled_platforms: (pub.enabled_platforms as string[]) || ['youtube', 'tiktok', 'instagram'],
    tts_short_engine: shortTts.engine,
    tts_short_voice: shortTts.voice,
    ai_plan: String(ai.plan || 'flux_pro'),
    max_ai_images_per_video: Number(ai.max_ai_images_per_video ?? 10),
  }
}

function normalizeForCompare(form: ChannelSettingsForm): Json {
  return {
    ...form,
    creative_brief: form.creative_brief || null,
    short_duration_s: Number(form.short_duration_s),
    long_quota: Number(form.long_quota),
    short_quota: Number(form.short_quota),
    enabled_platforms: [...form.enabled_platforms].sort(),
    max_ai_images_per_video: Number(form.max_ai_images_per_video),
  }
}

export function channelSettingsFormsEqual(a: ChannelSettingsForm, b: ChannelSettingsForm): boolean {
  return JSON.stringify(normalizeForCompare(a)) === JSON.stringify(normalizeForCompare(b))
}

/** Bloc `media_sources.ai_fallback` (enregistrement et aperçu de coût). */
export function aiFallbackPayload(form: ChannelSettingsForm): Json {
  return {
    plan: form.ai_plan,
    enabled: form.ai_plan !== 'off',
    max_ai_images_per_video: Number(form.max_ai_images_per_video),
  }
}

export function buildChannelUpdatePayload(
  form: ChannelSettingsForm,
  channel: Channel,
): {
  theme_category: string
  theme_prompt: string
  niche_prompt: string
  creative_brief: string | null
  config: Json
} {
  const config = { ...((channel.config || {}) as Json) }
  for (const key of LEGACY_CONFIG_KEYS) delete config[key]

  const { animations: _previousAnimations, visual_style: _previousVisualStyle, ...studio } = section(config, 'studio')
  const { min_short_duration_s: _min, max_short_duration_s: _max, ...production } = section(config, 'production')
  const { long: _long, style: _style, ...tts } = section(config, 'tts')

  return {
    theme_category: form.theme_category,
    theme_prompt: form.theme_prompt,
    niche_prompt: form.niche_prompt,
    creative_brief: form.creative_brief || null,
    config: {
      ...config,
      studio: {
        ...studio,
        ...(form.animations ? { animations: form.animations } : {}),
        ...(form.visual_style ? { visual_style: form.visual_style } : {}),
      },
      editorial: { ...section(config, 'editorial'), tone: form.tone },
      production: {
        ...production,
        mode: form.production_mode,
        short_duration_s: Number(form.short_duration_s),
      },
      publishing: {
        ...section(config, 'publishing'),
        daily_quotas: { long: Number(form.long_quota), short: Number(form.short_quota) },
        enabled_platforms: form.enabled_platforms,
        youtube_category_id: form.youtube_category_id,
      },
      tts: {
        ...tts,
        short: { engine: form.tts_short_engine, voice: form.tts_short_voice },
        gemini: { ...section(tts, 'gemini'), apply_to: 'off' },
      },
      media_sources: {
        ...section(config, 'media_sources'),
        ai_fallback: aiFallbackPayload(form),
      },
    },
  }
}
