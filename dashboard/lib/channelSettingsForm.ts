import type { Channel } from '@/lib/api'

export type ChannelSettingsForm = Record<string, unknown>

function resolveTtsProfiles(tts: Record<string, unknown>) {
  const gemini = (tts.gemini as Record<string, unknown>) || {}
  const defaultEngine = String(tts.engine || 'azure')
  const defaultVoice = String(tts.voice || 'fr-FR-Vivienne:DragonHDLatestNeural')
  const shortRaw = tts.short as Record<string, unknown> | undefined
  const longRaw = tts.long as Record<string, unknown> | undefined

  let shortEngine = String(shortRaw?.engine || defaultEngine)
  let shortVoice = String(shortRaw?.voice || defaultVoice)
  let longEngine = String(longRaw?.engine || defaultEngine)
  let longVoice = String(longRaw?.voice || defaultVoice)

  if (!shortRaw && !longRaw && gemini.apply_to && gemini.apply_to !== 'off') {
    const geminiVoice = String(gemini.voice || 'Leda')
    if (gemini.apply_to === 'shorts' || gemini.apply_to === 'both') {
      shortEngine = 'gemini'
      shortVoice = geminiVoice
    }
    if (gemini.apply_to === 'long' || gemini.apply_to === 'both') {
      longEngine = 'gemini'
      longVoice = geminiVoice
    }
  }

  return { shortEngine, shortVoice, longEngine, longVoice }
}

export function channelToFormState(channel: Channel): ChannelSettingsForm {
  const cfg = channel.config || {}
  const pub = (cfg.publishing as Record<string, unknown>) || {}
  const prod = (cfg.production as Record<string, unknown>) || {}
  const editorial = (cfg.editorial as Record<string, unknown>) || {}
  const tts = (cfg.tts as Record<string, unknown>) || {}
  const ttsProfiles = resolveTtsProfiles(tts)
  const media = (cfg.media_sources as Record<string, unknown>) || {}
  const mediaValidation = (cfg.media_validation as Record<string, unknown>) || {}
  const ai = (media.ai_fallback as Record<string, unknown>) || {}
  const runway = (cfg.runway as Record<string, unknown>) || {}

  return {
    theme_category: channel.theme_category || '',
    theme_prompt: channel.theme_prompt || '',
    niche_prompt: channel.niche_prompt || '',
    creative_brief: channel.creative_brief || '',
    media_validation_template: mediaValidation.media_validation_template || '',
    default_min_relevance_score: mediaValidation.default_min_relevance_score ?? '',
    youtube_category_id: String((pub.youtube_category_id as string) || '27'),
    tone: editorial.tone || '',
    target_audience: editorial.target_audience || '',
    differentiator: editorial.differentiator || '',
    production_mode: prod.mode || 'mixed',
    short_duration_s: prod.short_duration_s || 60,
    min_short_duration_s: prod.min_short_duration_s || 60,
    max_short_duration_s: prod.max_short_duration_s || 120,
    long_quota: (pub.daily_quotas as Record<string, number>)?.long ?? 1,
    short_quota: (pub.daily_quotas as Record<string, number>)?.short ?? 3,
    enabled_platforms: (pub.enabled_platforms as string[]) || ['youtube', 'tiktok', 'instagram'],
    tts_style: tts.style || 'narration-relaxed',
    tts_short_engine: ttsProfiles.shortEngine,
    tts_short_voice: ttsProfiles.shortVoice,
    tts_long_engine: ttsProfiles.longEngine,
    tts_long_voice: ttsProfiles.longVoice,
    ai_plan: ai.plan || 'flux_pro',
    ai_fallback_chain: ((ai.fallback_chain as string[]) || ['imagen3'])[0] || 'imagen3',
    max_images_per_segment: ai.max_images_per_segment ?? 2,
    max_ai_images_per_video: ai.max_ai_images_per_video ?? 10,
    max_ai_images_per_week: ai.max_ai_images_per_week ?? '',
    fallback_rate_override: ai.fallback_rate_override ?? '',
    runway_enabled: runway.enabled ?? false,
    runway_monthly_budget_usd: runway.monthly_budget_usd ?? 20,
    runway_max_clips_per_video: runway.max_clips_per_video ?? 3,
  }
}

function normalizeOptionalNumber(value: unknown): number | null {
  if (value === '' || value === null || value === undefined) return null
  const n = Number(value)
  return Number.isNaN(n) ? null : n
}

export function normalizeFormForCompare(form: ChannelSettingsForm): ChannelSettingsForm {
  const platforms = [...((form.enabled_platforms as string[]) || [])].sort()
  return {
    theme_category: String(form.theme_category || ''),
    theme_prompt: String(form.theme_prompt || ''),
    niche_prompt: String(form.niche_prompt || ''),
    creative_brief: String(form.creative_brief || '') || null,
    media_validation_template: String(form.media_validation_template || ''),
    default_min_relevance_score: normalizeOptionalNumber(form.default_min_relevance_score),
    youtube_category_id: String(form.youtube_category_id || '27'),
    tone: String(form.tone || ''),
    target_audience: String(form.target_audience || ''),
    differentiator: String(form.differentiator || ''),
    production_mode: String(form.production_mode || 'mixed'),
    short_duration_s: Number(form.short_duration_s),
    min_short_duration_s: Number(form.min_short_duration_s),
    max_short_duration_s: Number(form.max_short_duration_s),
    long_quota: Number(form.long_quota),
    short_quota: Number(form.short_quota),
    enabled_platforms: platforms,
    tts_style: String(form.tts_style || ''),
    tts_short_engine: String(form.tts_short_engine || 'azure'),
    tts_short_voice: String(form.tts_short_voice || ''),
    tts_long_engine: String(form.tts_long_engine || 'azure'),
    tts_long_voice: String(form.tts_long_voice || ''),
    ai_plan: String(form.ai_plan || 'off'),
    ai_fallback_chain: String(form.ai_fallback_chain || ''),
    max_images_per_segment: Number(form.max_images_per_segment),
    max_ai_images_per_video: Number(form.max_ai_images_per_video),
    max_ai_images_per_week: normalizeOptionalNumber(form.max_ai_images_per_week),
    fallback_rate_override: normalizeOptionalNumber(form.fallback_rate_override),
    runway_enabled: Boolean(form.runway_enabled),
    runway_monthly_budget_usd: Number(form.runway_monthly_budget_usd),
    runway_max_clips_per_video: Number(form.runway_max_clips_per_video),
  }
}

export function channelSettingsFormsEqual(
  a: ChannelSettingsForm,
  b: ChannelSettingsForm,
): boolean {
  return JSON.stringify(normalizeFormForCompare(a)) === JSON.stringify(normalizeFormForCompare(b))
}

export function buildChannelUpdatePayload(
  form: ChannelSettingsForm,
  channel: Channel,
): {
  theme_category: unknown
  theme_prompt: unknown
  niche_prompt: unknown
  creative_brief: string | null
  config: Record<string, unknown>
} {
  const existingConfig = (channel.config || {}) as Record<string, unknown>

  return {
    theme_category: form.theme_category,
    theme_prompt: form.theme_prompt,
    niche_prompt: form.niche_prompt,
    creative_brief: form.creative_brief ? String(form.creative_brief) : null,
    config: {
      ...existingConfig,
      editorial: {
        ...((existingConfig.editorial as Record<string, unknown>) || {}),
        tone: form.tone,
        target_audience: form.target_audience,
        differentiator: form.differentiator,
      },
      production: {
        ...((existingConfig.production as Record<string, unknown>) || {}),
        mode: form.production_mode,
        short_duration_s: Number(form.short_duration_s),
        min_short_duration_s: Number(form.min_short_duration_s),
        max_short_duration_s: Number(form.max_short_duration_s),
      },
      publishing: {
        ...((existingConfig.publishing as Record<string, unknown>) || {}),
        daily_quotas: { long: Number(form.long_quota), short: Number(form.short_quota) },
        enabled_platforms: form.enabled_platforms,
        youtube_category_id: form.youtube_category_id,
      },
      tts: {
        ...((existingConfig.tts as Record<string, unknown>) || {}),
        style: form.tts_style,
        short: {
          engine: form.tts_short_engine,
          voice: form.tts_short_voice,
        },
        long: {
          engine: form.tts_long_engine,
          voice: form.tts_long_voice,
        },
        gemini: {
          ...(((existingConfig.tts as Record<string, unknown>)?.gemini as Record<string, unknown>) || {}),
          apply_to: 'off',
        },
      },
      media_sources: {
        ...((existingConfig.media_sources as Record<string, unknown>) || {}),
        ai_fallback: {
          plan: form.ai_plan,
          enabled: form.ai_plan !== 'off',
          fallback_chain: form.ai_fallback_chain ? [form.ai_fallback_chain] : [],
          max_images_per_segment: Number(form.max_images_per_segment),
          max_ai_images_per_video: Number(form.max_ai_images_per_video),
          max_ai_images_per_week: form.max_ai_images_per_week
            ? Number(form.max_ai_images_per_week)
            : null,
          fallback_rate_override: form.fallback_rate_override
            ? Number(form.fallback_rate_override)
            : null,
        },
      },
      runway: {
        ...((existingConfig.runway as Record<string, unknown>) || {}),
        enabled: Boolean(form.runway_enabled),
        monthly_budget_usd: Number(form.runway_monthly_budget_usd),
        max_clips_per_video: Number(form.runway_max_clips_per_video),
      },
      media_validation: {
        ...((existingConfig.media_validation as Record<string, unknown>) || {}),
        media_validation_template: form.media_validation_template || '',
        default_min_relevance_score: form.default_min_relevance_score
          ? Number(form.default_min_relevance_score)
          : null,
      },
    },
  }
}
