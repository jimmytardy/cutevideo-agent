const BASE = '/api/v1'

export interface Channel {
  id: string
  slug: string
  name: string
  theme_category: string
  niche_prompt: string | null
  theme_prompt?: string | null
  brand_kit?: Record<string, unknown> | null
  onboarding_step?: string
  tiktok_publish_defaults?: Record<string, unknown> | null
  instagram_profile?: Record<string, unknown> | null
  config: Record<string, unknown> | null
  youtube_channel_id: string | null
  youtube_channel_url: string | null
  instagram_page_id: string | null
  tiktok_enabled: boolean
  composio_user_id: string
  composio_tiktok_account_id: string | null
  max_concurrent_pipelines: number
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface ThemeVariant {
  content_angle: string
  slug: string
  name: string
  theme_category: string
  niche_prompt: string
  suggested_tags: string[]
}

export interface RecommendedTheme extends ThemeVariant {
  differentiation_score: number
  competition_level: string
  why_you_can_win: string
  risks: string[]
}

export interface MarketAnalysisReport {
  id?: string | null
  user_prompt: string
  market_summary: string
  saturation_verdict: string
  differentiation_verdict: string
  platforms_analyzed: string[]
  platform_insights: {
    platform: string
    trend_summary: string
    winning_formats: string[]
    audience_signals: string[]
    hashtag_or_keyword_hints: string[]
    data_source: string
  }[]
  top_competitors: {
    platform: string
    name: string
    handle_or_url: string
    subscriber_count: number | null
    video_count: number | null
    positioning: string
    strengths: string[]
    weaknesses: string[]
    content_formats: string[]
  }[]
  niche_opportunities: {
    niche_name: string
    potential_score: number
    competition_level: string
    rationale: string
    differentiation_angle: string
  }[]
  recommended_themes: RecommendedTheme[]
  avoid: string[]
  next_steps: string[]
}

export interface MarketAnalysisListItem {
  id: string
  prompt: string
  saturation_verdict: string | null
  market_summary: string | null
  platforms_analyzed: string[] | null
  created_at: string
}

export interface MarketAnalysisDetail extends MarketAnalysisListItem {
  report: MarketAnalysisReport | null
}

export interface ChannelBrandKit {
  slug: string
  name: string
  theme_category: string
  niche_prompt: string
  content_angle: string
  youtube: {
    title: string
    description: string
    keywords: string[]
    handle_suggestion: string
  }
  tiktok: { display_name: string; bio: string; default_caption_style: string }
  instagram: { page_name: string; bio: string }
  default_tags: string[]
  media_source_priority?: string[]
  sample_video_titles?: string[]
}

export interface YouTubeChannelItem {
  channel_id: string
  title: string
  description: string
  custom_url: string
}

export interface ChannelIntegrations {
  tiktok_connected: boolean
  tiktok_enabled: boolean
  youtube_configured: boolean
  instagram_configured: boolean
}

export interface Project {
  id: string
  channel_id: string
  channel_name: string | null
  theme: string
  title: string | null
  target_duration_seconds: number | null
  status: string
  error_message: string | null
  config: Record<string, unknown> | null
  created_at: string
  updated_at: string
}

export interface AgentRun {
  id: string
  project_id: string
  agent_name: string | null
  status: string | null
  iteration: number
  input_json: Record<string, unknown> | null
  output_json: Record<string, unknown> | null
  error: string | null
  started_at: string | null
  ended_at: string | null
}

export interface MediaAsset {
  id: string
  project_id: string
  segment_order: number | null
  source: string | null
  source_url: string | null
  local_path: string | null
  license: string | null
  attribution: string | null
  asset_type: string | null
  selected: boolean
  created_at: string
}

export interface CriticReport {
  id: string
  video_id: string
  iteration: number | null
  decision: string | null
  global_score: number | null
  feedback: Record<string, unknown> | null
  requested_changes: Array<Record<string, string>> | null
  created_at: string
}

export interface Video {
  id: string
  project_id: string
  video_type: string | null
  local_path: string | null
  duration_s: number | null
  iteration: number
  status: string
  created_at: string
}

const fetcher = async (url: string) => {
  const r = await fetch(url)
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(body?.detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export { fetcher }

export interface RunwayStatus {
  enabled: boolean
  monthly_budget_usd: number
  spent_usd: number
  remaining_usd: number
  credit_error: boolean
  model: string
  cost_per_clip_usd: number
}

export async function fetchRunwayStatus(channelId: string): Promise<RunwayStatus> {
  return fetcher(`${BASE}/channels/${channelId}/runway-status`)
}

export async function fetchChannels(activeOnly = false): Promise<Channel[]> {
  const q = activeOnly ? '?active_only=true' : ''
  const res = await fetch(`${BASE}/channels${q}`)
  return res.json()
}

export async function createChannel(data: {
  slug: string
  name: string
  theme_category: string
  niche_prompt?: string
}): Promise<Channel> {
  const res = await fetch(`${BASE}/channels`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return res.json()
}

export async function fetchChannelIntegrations(channelId: string): Promise<ChannelIntegrations> {
  const res = await fetch(`${BASE}/channels/${channelId}/integrations`)
  return res.json()
}

export async function connectTikTok(channelId: string): Promise<{ redirect_url: string; connection_id: string }> {
  const res = await fetch(`${BASE}/channels/${channelId}/connect/tiktok`, { method: 'POST' })
  return res.json()
}

export async function createProject(
  channelId: string,
  theme: string,
  target_duration_seconds: number,
): Promise<Project> {
  const res = await fetch(`${BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ channel_id: channelId, theme, target_duration_seconds }),
  })
  return res.json()
}

export async function runPipeline(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}/run`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Échec du lancement du pipeline')
  }
}

export async function deleteProject(projectId: string): Promise<void> {
  await fetch(`${BASE}/projects/${projectId}`, { method: 'DELETE' })
}

export async function analyzeMarket(
  prompt: string,
  platforms: string[] = ['youtube', 'tiktok', 'instagram'],
): Promise<MarketAnalysisReport> {
  const res = await fetch(`${BASE}/channels/onboarding/market-analysis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, platforms }),
  })
  if (!res.ok) {
    throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur analyse marché')
  }
  return res.json()
}

export async function suggestThemes(
  prompt: string,
  marketContext?: string | null,
): Promise<ThemeVariant[]> {
  const res = await fetch(`${BASE}/channels/onboarding/suggest-themes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, market_context: marketContext ?? undefined }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur suggest-themes')
  const data = await res.json()
  return data.variants
}

export async function generateBrandKit(
  variant: ThemeVariant,
  marketContext?: string | null,
): Promise<ChannelBrandKit> {
  const res = await fetch(`${BASE}/channels/onboarding/generate-brand`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant, market_context: marketContext ?? undefined }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur generate-brand')
  return res.json()
}

export async function createOnboardingDraft(
  themePrompt: string,
  brandKit: ChannelBrandKit,
): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/onboarding/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme_prompt: themePrompt, brand_kit: brandKit }),
  })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur draft')
  return res.json()
}

export async function getYoutubeOAuthUrl(channelId?: string): Promise<{ authorization_url: string; state: string }> {
  const q = channelId ? `?channel_id=${channelId}` : ''
  const res = await fetch(`${BASE}/channels/youtube/oauth-url${q}`)
  return res.json()
}

export async function listYoutubeChannels(channelId?: string): Promise<YouTubeChannelItem[]> {
  const q = channelId ? `?channel_id=${channelId}` : ''
  const res = await fetch(`${BASE}/channels/youtube/list${q}`)
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur liste YouTube')
  return res.json()
}

export async function patchOnboardingYoutube(
  channelId: string,
  data: { youtube_channel_id: string; youtube_channel_url?: string },
): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/${channelId}/onboarding/youtube`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return res.json()
}

export async function applyYoutubeBranding(channelId: string): Promise<void> {
  const res = await fetch(`${BASE}/channels/${channelId}/apply-youtube-branding`, { method: 'POST' })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || 'Erreur branding YouTube')
}

export async function patchOnboardingTiktok(
  channelId: string,
  tiktok_publish_defaults: Record<string, unknown>,
): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/${channelId}/onboarding/tiktok`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tiktok_publish_defaults }),
  })
  return res.json()
}

export async function patchOnboardingInstagram(
  channelId: string,
  data: { instagram_page_id: string; instagram_profile?: Record<string, unknown> },
): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/${channelId}/onboarding/instagram`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  return res.json()
}

export async function completeOnboarding(channelId: string): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/${channelId}/onboarding/complete`, { method: 'POST' })
  return res.json()
}

export async function fetchChannel(channelId: string): Promise<Channel> {
  const res = await fetch(`${BASE}/channels/${channelId}`)
  return res.json()
}

export async function fetchProjectVideos(projectId: string): Promise<Video[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/videos`)
  if (!res.ok) return []
  return res.json()
}

export async function publishProject(projectId: string, platform: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur publication')
  }
}

export async function listMarketAnalyses(): Promise<MarketAnalysisListItem[]> {
  const res = await fetch(`${BASE}/markets`)
  if (!res.ok) throw new Error('Erreur chargement analyses marché')
  return res.json()
}

export async function getMarketAnalysis(id: string): Promise<MarketAnalysisDetail> {
  const res = await fetch(`${BASE}/markets/${id}`)
  if (!res.ok) throw new Error('Analyse introuvable')
  return res.json()
}
