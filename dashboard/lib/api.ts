const BASE = '/api/v1'

export interface Channel {
  id: string
  slug: string
  name: string
  theme_category: string
  niche_prompt: string | null
  theme_prompt?: string | null
  creative_brief?: string | null
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
  beat_index: number | null
  source: string | null
  source_url: string | null
  local_path: string | null
  license: string | null
  attribution: string | null
  asset_type: string | null
  selected: boolean
  relevance_score: number | null
  relevance_reason: string | null
  library_status: string | null
  generation_prompt: string | null
  visual_type: string | null
  iteration: number | null
  created_at: string
}

export interface MediaRelevanceScoreEntry {
  score: number
  reason: string
  title?: string
  url?: string
  rejection_category?: string
}

export interface MediaRelevanceSegmentLog {
  segment_order: number
  scores?: MediaRelevanceScoreEntry[]
  source?: string
  attempt?: number
  phase?: string
  generation_failed?: boolean
  validation_relaxed?: boolean
  total_raw_candidates?: number
  passing_count?: number
  niche_risk?: string
  from_phase?: string
  score?: number
}

export interface MediaProgress {
  iteration: number
  found: number
  total: number
  percent: number
  segments_done: number
  segments_total: number
  agent_status: string
}

export interface MediaValidationOverride {
  must_include?: string[]
  must_exclude?: string[]
  validation_prompt?: string | null
  min_relevance_score?: number | null
}

export interface MediaValidationBrief {
  subject_entity: string
  subject_type: string
  must_include: string[]
  must_exclude: string[]
  ambiguity_warnings: string[]
  validation_prompt: string
  min_relevance_score: number
  niche_risk: string
  segments: Record<string, Record<string, unknown>>
  override?: MediaValidationOverride | null
  source: string
}

export interface VideoAnalysisIssue {
  type: string
  severity: 'low' | 'medium' | 'high'
  timestamp_s: number
  description: string
}

export interface VideoAnalysis {
  analysis_status?: 'ok' | 'missing_key' | 'file_not_found' | 'error' | 'no_local_path'
  score: number
  issues: VideoAnalysisIssue[]
  visual_coherence: number
  subtitle_quality: number
  rhythm: number
  summary: string
}

export interface DeliveryStyle {
  pace?: string
  emotion?: string
  azure_style?: string
  emphasis_words?: string[]
}

export interface VisualBeat {
  order: number
  phrase_anchor: string
  visual_type: string
  prompt: string
  style_hint?: string
  on_screen_text?: string
  duration_hint_s?: number | null
}

export interface ScenarioSegment {
  order?: number
  title?: string
  duration_s?: number
  needs_voice?: boolean
  needs_music?: boolean
  narration_text?: string
  narration?: string
  on_screen_text?: string
  search_keywords?: string[]
  source_hint?: string[]
  mood?: string
  strip_source_audio?: boolean
  hook_type?: string | null
  delivery_style?: DeliveryStyle
  visual_suggestion?: string
  visual_beats?: VisualBeat[]
}

export interface ResearchBrief {
  subject_entity: string
  key_facts: string[]
  timeline: Array<{ year?: string; event?: string }>
  sources: Array<{ title?: string; url?: string; snippet?: string }>
  visual_anchors: string[]
  common_misconceptions: string[]
  narrative_angles: string[]
  confidence: number
  niche_risk: string
}

export interface Scenario {
  id: string
  project_id: string
  segments: ScenarioSegment[] | null
  total_duration_s: number | null
  iteration: number
  created_at: string
}

export interface AudioFile {
  id: string
  project_id: string
  segment_order: number | null
  local_path: string | null
  duration_s: number | null
  tts_engine: string | null
  voice: string | null
  transcript: string | null
  word_timestamps: Array<{ word: string; start: number; end: number }> | null
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
  video_analysis: VideoAnalysis | null
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

export interface FinalPreview {
  video: Video | null
  stream_url: string | null
  subtitles_available: boolean
  subtitles_download_url: string | null
  subtitles_note: string | null
}

const MAX_FETCH_RETRIES = 3

async function fetchWithRetry(url: string, init?: RequestInit): Promise<Response> {
  let lastError: unknown
  for (let attempt = 0; attempt < MAX_FETCH_RETRIES; attempt++) {
    try {
      const response = await fetch(url, init)
      if (response.ok || (response.status < 500 && response.status !== 408)) {
        return response
      }
      if (attempt < MAX_FETCH_RETRIES - 1) {
        await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)))
        continue
      }
      return response
    } catch (error) {
      lastError = error
      if (attempt < MAX_FETCH_RETRIES - 1) {
        await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)))
        continue
      }
      throw error
    }
  }
  throw lastError
}

const fetcher = async (url: string) => {
  const r = await fetchWithRetry(url)
  if (!r.ok) {
    const body = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(body?.detail ?? `HTTP ${r.status}`)
  }
  return r.json()
}

export function swrOnErrorRetry(
  error: unknown,
  _key: string,
  _config: unknown,
  revalidate: (options: { retryCount: number }) => void,
  { retryCount }: { retryCount: number },
): void {
  if (retryCount >= 3) return
  const message = error instanceof Error ? error.message : String(error)
  if (/HTTP 4\d\d/.test(message)) return
  setTimeout(() => revalidate({ retryCount }), 1000 * (retryCount + 1))
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

export async function stopPipeline(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}/stop`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Échec de l\'arrêt du pipeline')
  }
}

export async function restartPipeline(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}/restart`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || 'Échec du redémarrage du pipeline')
  }
}

export async function runFromStep(projectId: string, step: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}/run-from/${step}`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || `Échec du redémarrage depuis ${step}`)
  }
}

export async function restartFromCriticIteration(
  projectId: string,
  reportId: string,
): Promise<{ critic_start_from: string }> {
  const res = await fetch(`${BASE}/projects/${projectId}/restart-from-critic/${reportId}`, { method: 'POST' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur relance depuis itération critique')
  }
  return res.json()
}

export async function fetchCriticReports(projectId: string): Promise<CriticReport[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/critic-reports`)
  if (!res.ok) return []
  return res.json()
}

export async function deleteProject(projectId: string): Promise<void> {
  const res = await fetch(`${BASE}/projects/${projectId}`, { method: 'DELETE' })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur suppression du projet')
  }
}

export async function updateProjectMaxIterations(projectId: string, maxIterations: number): Promise<Project> {
  const res = await fetch(`${BASE}/projects/${projectId}/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_critic_iterations: maxIterations }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur mise à jour config')
  }
  return res.json()
}

export async function fetchProjectMediaValidation(projectId: string): Promise<MediaValidationBrief> {
  const res = await fetch(`${BASE}/projects/${projectId}/media-validation`)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Brief validation introuvable')
  }
  return res.json()
}

export async function updateProjectMediaValidation(
  projectId: string,
  override: MediaValidationOverride,
): Promise<MediaValidationBrief> {
  const res = await fetch(`${BASE}/projects/${projectId}/media-validation`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(override),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur mise à jour validation')
  }
  return res.json()
}

export async function regenerateProjectMediaValidation(
  projectId: string,
): Promise<{ brief: MediaValidationBrief; message: string }> {
  const res = await fetch(`${BASE}/projects/${projectId}/media-validation/regenerate`, {
    method: 'POST',
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error((err as { detail?: string }).detail || 'Erreur régénération brief')
  }
  return res.json()
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

export async function fetchProjectScenario(projectId: string): Promise<Scenario | null> {
  const res = await fetch(`${BASE}/projects/${projectId}/scenario`)
  if (!res.ok) return null
  return res.json()
}

export async function fetchProjectMediaAssets(projectId: string): Promise<MediaAsset[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/media-assets`)
  if (!res.ok) return []
  return res.json()
}

export function mediaProgressUrl(projectId: string, iteration?: number): string {
  const base = `${BASE}/projects/${projectId}/media-progress`
  if (iteration != null) return `${base}?iteration=${iteration}`
  return base
}

export async function fetchProjectMediaProgress(
  projectId: string,
  iteration?: number,
): Promise<MediaProgress | null> {
  const res = await fetch(mediaProgressUrl(projectId, iteration))
  if (!res.ok) return null
  return res.json()
}

export async function fetchProjectAudio(projectId: string): Promise<AudioFile[]> {
  const res = await fetch(`${BASE}/projects/${projectId}/audio`)
  if (!res.ok) return []
  return res.json()
}

export interface HealthStatus {
  status: 'ok' | 'degraded'
  database: 'ok' | 'error'
  redis: 'ok' | 'error'
  scheduler: 'running' | 'stopped'
  s3: 'ok' | 'error'
  s3_detail: string | null
}

export interface SchedulerJob {
  id: string
  name: string
  next_run_time: string | null
  last_run: {
    status: string
    started_at: string | null
    ended_at: string | null
    error: string | null
  } | null
}

export interface StorageStats {
  used_bytes: number
  max_bytes: number
  used_pct: number
  bucket: string | null
}

export async function fetchHealth(): Promise<HealthStatus> {
  return fetcher('/health')
}

export async function fetchStorageStats(): Promise<StorageStats> {
  return fetcher('/storage/stats')
}

export async function fetchSchedulerJobs(): Promise<SchedulerJob[]> {
  return fetcher(`${BASE}/scheduler/jobs`)
}

export async function fetchProjectsByStatus(status: string, limit = 20): Promise<Project[]> {
  return fetcher(`${BASE}/projects?status=${encodeURIComponent(status)}&limit=${limit}`)
}

export async function fetchRecentProjects(limit = 10): Promise<Project[]> {
  return fetcher(`${BASE}/projects?limit=${limit}`)
}

export interface SimilarTopic {
  title: string | null
  theme: string | null
  created_at: string | null
}

export interface SimilarityCheck {
  is_duplicate: boolean
  similar_topics: SimilarTopic[]
}

export async function checkTopicSimilarity(
  channelId: string,
  theme: string,
): Promise<SimilarityCheck> {
  const params = new URLSearchParams({ channel_id: channelId, theme })
  return fetcher(`${BASE}/projects/check-similarity?${params}`)
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
