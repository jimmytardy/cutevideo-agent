const BASE = '/api/v1'
const AUTH_TOKEN_KEY = 'cutevideo_auth_token'

export function getAuthToken(): string | null {
  if (typeof window === 'undefined') return null
  return localStorage.getItem(AUTH_TOKEN_KEY)
}

export function setAuthToken(token: string): void {
  localStorage.setItem(AUTH_TOKEN_KEY, token)
}

export function clearAuthToken(): void {
  localStorage.removeItem(AUTH_TOKEN_KEY)
}

export function authHeaders(): HeadersInit {
  const token = getAuthToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** URL média avec JWT en query string (balises video/img ne supportent pas Authorization). */
export function authenticatedMediaUrl(path: string): string {
  const token = getAuthToken()
  if (!token) return path
  const sep = path.includes('?') ? '&' : '?'
  return `${path}${sep}access_token=${encodeURIComponent(token)}`
}

export interface AuthUser {
  id: string
  email: string
  display_name: string | null
  avatar_url: string | null
  plan_slug: string
  is_admin: boolean
}

export interface SubscriptionInfo {
  plan_slug: string
  plan_name: string
  is_unlimited: boolean
  limits: Record<string, unknown>
  usage: Record<string, unknown>
}

export async function getGoogleLoginUrl(): Promise<{ authorization_url: string; state: string }> {
  const redirectAfter = `${window.location.origin}/login`
  const res = await fetch(`${BASE}/auth/google/login?redirect_after=${encodeURIComponent(redirectAfter)}`)
  if (!res.ok) throw new Error('Impossible de démarrer la connexion Google')
  return res.json()
}

export async function fetchMe(): Promise<AuthUser> {
  return fetcher(`${BASE}/auth/me`)
}

export async function fetchMySubscription(): Promise<SubscriptionInfo> {
  return fetcher(`${BASE}/me/subscription`)
}

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
  queue_position?: number | null
  queue_length?: number | null
  queued_at?: string | null
}

export interface PipelineQueueStatus {
  position: number
  queue_length: number
  priority: number
  queued_at: string | null
  blocked_reason: string | null
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
  cost_estimate_usd: number | null
  llm_input_tokens: number | null
  llm_output_tokens: number | null
  llm_model: string | null
}

export interface ProjectCost {
  project_id: string
  total_usd: number
  cap_usd: number
  iterations_used: number
  max_iterations: number | null
  stop_reason: string
  by_agent: Array<{
    agent_name: string
    usd: number
    input_tokens: number
    output_tokens: number
  }>
  by_iteration: Array<{
    iteration: number
    usd: number
    duration_s: number
  }>
  elapsed_s: number
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

export interface AgentProgressItem {
  done: number
  total: number
  percent: number
  detail?: string | null
  segments_done?: number | null
  segments_total?: number | null
}

export interface PipelineProgressResponse {
  preparation: Record<string, AgentProgressItem>
  iterations: Record<string, Record<string, AgentProgressItem>>
  post_production: Record<string, AgentProgressItem>
}

export interface PipelinePlanResponse {
  is_short: boolean
  preparation: string[]
  iteration_first: string[]
  iteration_revision: string[]
  post_production: string[]
  max_iterations: number
  max_iterations_unlimited?: boolean
}

export interface BeatValidationResolved {
  segment_order: number
  beat_order: number | null
  segment_title: string
  visual_type: string | null
  phrase_anchor: string | null
  prompt: string | null
  must_include: string[]
  must_exclude: string[]
  validation_prompt: string
  min_relevance_score: number
  layers: string[]
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
  resolved_beats: BeatValidationResolved[]
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
  diagram_labels?: Array<{ text?: string; position?: string }>
  diagram_brief?: { layout?: string; key_elements?: string[]; fallback_visual_type?: string }
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

export interface OutlineSegment {
  order: number
  title: string
  duration_s: number
  needs_voice: boolean
  needs_music: boolean
  mood: string
  hook_type?: string | null
  strip_source_audio: boolean
  intent: string
}

export interface EditorialOutline {
  title: string
  description: string
  segments: OutlineSegment[]
  total_duration_s: number
}

export interface ProjectMetadata {
  title: string
  description: string
  tags: string[]
  chapters: Array<{ start_s?: number; title?: string }>
}

export interface ThumbnailCandidate {
  local_path: string | null
  prompt: string | null
  attribution: string | null
  primary: boolean
  ctr_score?: number | null
}

export function projectThumbnailStreamUrl(projectId: string, index: number): string {
  return authenticatedMediaUrl(`/api/v1/projects/${projectId}/thumbnails/${index}/stream`)
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
  iteration: number
  segment_order: number | null
  local_path: string | null
  duration_s: number | null
  tts_engine: string | null
  voice: string | null
  transcript: string | null
  word_timestamps: Array<{ word: string; start: number; end: number }> | null
  created_at: string
}

export interface EffectiveBeat {
  order: number
  phrase_anchor: string
  visual_type: string
  on_screen_text: string
  adaptation: string
  source_beat_orders: number[]
}

export interface BeatClipPlan {
  beat_order: number
  source_beat_orders: number[]
  asset_path: string
  asset_type: string
  timeline_start_s: number
  timeline_end_s: number
  source_trim_start_s: number
  source_trim_end_s: number | null
  trim_reason: string
  on_screen_text: string
  audio_lead_s?: number
  audio_trail_s?: number
}

export interface SegmentMontagePlan {
  segment_order: number
  effective_beats: EffectiveBeat[]
  clips: BeatClipPlan[]
  adaptation_notes: string
  music_path?: string
}

export interface MontagePlan {
  id: string
  project_id: string
  iteration: number
  segments: SegmentMontagePlan[]
  planner_notes: string
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
  duration_warnings: string[]
}

const MAX_FETCH_RETRIES = 3

async function fetchWithRetry(url: string, init?: RequestInit): Promise<Response> {
  let lastError: unknown
  const mergedInit: RequestInit = {
    ...init,
    headers: {
      ...authHeaders(),
      ...(init?.headers ?? {}),
    },
  }
  for (let attempt = 0; attempt < MAX_FETCH_RETRIES; attempt++) {
    try {
      const response = await fetch(url, mergedInit)
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

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json().catch(() => ({ detail: response.statusText }))
    throw new Error(body?.detail ?? `HTTP ${response.status}`)
  }
  // Réponses sans corps (204 No Content, DELETE, …) : ne pas tenter de parser
  // du JSON sur un body vide, sinon "Unexpected end of JSON input".
  if (response.status === 204) {
    return undefined as T
  }
  const text = await response.text()
  if (!text) {
    return undefined as T
  }
  return JSON.parse(text) as T
}

async function apiJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetchWithRetry(url, init)
  return parseJsonResponse<T>(response)
}

const fetcher = async <T,>(url: string): Promise<T> => apiJson<T>(url)

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
  return apiJson<Channel[]>(`${BASE}/channels${q}`)
}

export async function createChannel(data: {
  slug: string
  name: string
  theme_category: string
  niche_prompt?: string
}): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function fetchChannelIntegrations(channelId: string): Promise<ChannelIntegrations> {
  return apiJson<ChannelIntegrations>(`${BASE}/channels/${channelId}/integrations`)
}

export async function connectTikTok(channelId: string): Promise<{ redirect_url: string; connection_id: string }> {
  return apiJson<{ redirect_url: string; connection_id: string }>(
    `${BASE}/channels/${channelId}/connect/tiktok`,
    { method: 'POST' },
  )
}

export async function createProject(
  channelId: string,
  theme: string,
  target_duration_seconds: number,
  config?: Record<string, unknown>,
): Promise<Project> {
  return apiJson<Project>(`${BASE}/projects`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      channel_id: channelId,
      theme,
      target_duration_seconds,
      config,
    }),
  })
}

export async function runPipeline(projectId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/run`, { method: 'POST' })
}

export async function stopPipeline(projectId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/stop`, { method: 'POST' })
}

export async function restartPipeline(projectId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/restart`, { method: 'POST' })
}

export async function dequeueProject(projectId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/queue`, { method: 'DELETE' })
}

export async function fetchQueueStatus(projectId: string): Promise<PipelineQueueStatus> {
  return fetcher(`${BASE}/projects/${projectId}/queue-status`)
}

export async function runFromStep(projectId: string, step: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/run-from/${step}`, { method: 'POST' })
}

export async function restartFromCriticIteration(
  projectId: string,
  reportId: string,
): Promise<{ critic_start_from: string }> {
  return apiJson<{ critic_start_from: string }>(
    `${BASE}/projects/${projectId}/restart-from-critic/${reportId}`,
    { method: 'POST' },
  )
}

export async function fetchCriticReports(projectId: string): Promise<CriticReport[]> {
  const res = await fetchWithRetry(`${BASE}/projects/${projectId}/critic-reports`)
  if (!res.ok) return []
  return res.json()
}

export async function fetchProjectCost(projectId: string): Promise<ProjectCost | null> {
  const res = await fetchWithRetry(`${BASE}/projects/${projectId}/cost`)
  if (!res.ok) return null
  return res.json()
}

export async function deleteProject(projectId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}`, { method: 'DELETE' })
}

export async function updateProjectMaxIterations(projectId: string, maxIterations: number): Promise<Project> {
  return apiJson<Project>(`${BASE}/projects/${projectId}/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_critic_iterations: maxIterations }),
  })
}

export async function clearProjectMaxIterations(projectId: string): Promise<Project> {
  return apiJson<Project>(`${BASE}/projects/${projectId}/config`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ max_critic_iterations: null }),
  })
}

export async function fetchProjectMediaValidation(projectId: string): Promise<MediaValidationBrief> {
  return apiJson<MediaValidationBrief>(`${BASE}/projects/${projectId}/media-validation`)
}

export async function analyzeMarket(
  prompt: string,
  platforms: string[] = ['youtube', 'tiktok', 'instagram'],
): Promise<MarketAnalysisReport> {
  return apiJson<MarketAnalysisReport>(`${BASE}/channels/onboarding/market-analysis`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, platforms }),
  })
}

export async function suggestThemes(
  prompt: string,
  marketContext?: string | null,
): Promise<ThemeVariant[]> {
  const data = await apiJson<{ variants: ThemeVariant[] }>(`${BASE}/channels/onboarding/suggest-themes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ prompt, market_context: marketContext ?? undefined }),
  })
  return data.variants
}

export async function generateBrandKit(
  variant: ThemeVariant,
  marketContext?: string | null,
): Promise<ChannelBrandKit> {
  return apiJson<ChannelBrandKit>(`${BASE}/channels/onboarding/generate-brand`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ variant, market_context: marketContext ?? undefined }),
  })
}

export async function createOnboardingDraft(
  themePrompt: string,
  brandKit: ChannelBrandKit,
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/onboarding/draft`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ theme_prompt: themePrompt, brand_kit: brandKit }),
  })
}

export async function getYoutubeOAuthUrl(channelId?: string): Promise<{ authorization_url: string; state: string }> {
  const q = channelId ? `?channel_id=${channelId}` : ''
  return apiJson<{ authorization_url: string; state: string }>(`${BASE}/channels/youtube/oauth-url${q}`)
}

export async function listYoutubeChannels(channelId?: string): Promise<YouTubeChannelItem[]> {
  const q = channelId ? `?channel_id=${channelId}` : ''
  return apiJson<YouTubeChannelItem[]>(`${BASE}/channels/youtube/list${q}`)
}

export async function disconnectYoutubeOAuth(channelId: string): Promise<void> {
  await apiJson<{ status: string }>(`${BASE}/channels/${channelId}/youtube/oauth`, { method: 'DELETE' })
}

export async function patchOnboardingYoutube(
  channelId: string,
  data: { youtube_channel_id: string; youtube_channel_url?: string },
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}/onboarding/youtube`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function applyYoutubeBranding(channelId: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/channels/${channelId}/apply-youtube-branding`, { method: 'POST' })
}

export async function skipOnboardingStep(
  channelId: string,
  step: 'youtube' | 'tiktok' | 'instagram',
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}/onboarding/skip/${step}`, { method: 'POST' })
}

export async function patchOnboardingTiktok(
  channelId: string,
  tiktok_publish_defaults: Record<string, unknown>,
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}/onboarding/tiktok`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tiktok_publish_defaults }),
  })
}

export async function patchOnboardingInstagram(
  channelId: string,
  data: { instagram_page_id: string; instagram_profile?: Record<string, unknown> },
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}/onboarding/instagram`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function completeOnboarding(channelId: string): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}/onboarding/complete`, { method: 'POST' })
}

export interface ChannelUpdatePayload {
  theme_category?: unknown
  theme_prompt?: unknown
  niche_prompt?: unknown
  creative_brief?: string | null
  config?: Record<string, unknown>
}

export interface ChannelCostEstimate {
  ai_images: {
    plan: string
    plan_label: string
    provider_family: string
    cost_per_image_eur: number
    images_per_week: number
    cost_eur_per_week: number
    cost_eur_per_month: number
    breakdown: {
      theme_category: string
      fallback_rate: number
      videos_per_week: number
      segments_per_week: number
    }
  }
  total_eur_per_week: number
}

export interface ChannelCostPreviewRequest {
  ai_fallback: {
    plan?: unknown
    enabled?: boolean
    fallback_chain?: unknown[]
    max_images_per_segment?: number
    max_ai_images_per_video?: number
    max_ai_images_per_week?: number | null
    fallback_rate_override?: number | null
  }
}

export async function updateChannel(
  channelId: string,
  data: ChannelUpdatePayload,
): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function previewChannelCostEstimate(
  channelId: string,
  data: ChannelCostPreviewRequest,
): Promise<ChannelCostEstimate> {
  return apiJson<ChannelCostEstimate>(`${BASE}/channels/${channelId}/cost-estimate/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

export async function fetchChannel(channelId: string): Promise<Channel> {
  return apiJson<Channel>(`${BASE}/channels/${channelId}`)
}

export async function fetchProjectVideos(projectId: string): Promise<Video[]> {
  const res = await fetchWithRetry(`${BASE}/projects/${projectId}/videos`)
  if (!res.ok) return []
  return res.json()
}

export async function publishProject(projectId: string, platform: string): Promise<void> {
  await apiJson<unknown>(`${BASE}/projects/${projectId}/publish`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ platform }),
  })
}

export function projectScenarioUrl(
  projectId: string,
  opts?: { scenarioId?: string; atAgent?: string; iteration?: number },
): string {
  const base = `${BASE}/projects/${projectId}/scenario`
  const params = new URLSearchParams()
  if (opts?.scenarioId) params.set('scenario_id', opts.scenarioId)
  if (opts?.atAgent) params.set('at_agent', opts.atAgent)
  if (opts?.iteration != null) params.set('iteration', String(opts.iteration))
  const qs = params.toString()
  return qs ? `${base}?${qs}` : base
}

export async function fetchProjectScenario(
  projectId: string,
  opts?: { scenarioId?: string; atAgent?: string },
): Promise<Scenario | null> {
  const res = await fetchWithRetry(projectScenarioUrl(projectId, opts))
  if (!res.ok) return null
  return res.json()
}

export async function fetchProjectMediaAssets(projectId: string): Promise<MediaAsset[]> {
  const res = await fetchWithRetry(`${BASE}/projects/${projectId}/media-assets`)
  if (!res.ok) return []
  return res.json()
}

export function pipelineProgressUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/pipeline-progress`
}

export function pipelinePlanUrl(projectId: string): string {
  return `${BASE}/projects/${projectId}/pipeline-plan`
}

export async function fetchProjectPipelineProgress(
  projectId: string,
): Promise<PipelineProgressResponse | null> {
  const res = await fetchWithRetry(pipelineProgressUrl(projectId))
  if (!res.ok) return null
  return res.json()
}

export function mediaProgressUrl(projectId: string, iteration?: number): string {
  const base = `${BASE}/projects/${projectId}/media-progress`
  if (iteration != null) return `${base}?iteration=${iteration}`
  return base
}

export function montagePlanUrl(projectId: string, iteration?: number): string {
  const base = `${BASE}/projects/${projectId}/montage-plan`
  if (iteration != null) return `${base}?iteration=${iteration}`
  return base
}

export async function fetchProjectMediaProgress(
  projectId: string,
  iteration?: number,
): Promise<MediaProgress | null> {
  const res = await fetchWithRetry(mediaProgressUrl(projectId, iteration))
  if (!res.ok) return null
  return res.json()
}

export async function fetchProjectAudio(projectId: string): Promise<AudioFile[]> {
  const res = await fetchWithRetry(`${BASE}/projects/${projectId}/audio`)
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
  description?: string
  schedule?: string
  next_run_at: string | null
  last_run: {
    status: string
    started_at: string | null
    ended_at: string | null
    duration_s?: number | null
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

export async function fetchUpcomingJobs(): Promise<SchedulerJob[]> {
  return fetcher(`${BASE}/scheduler/upcoming`)
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
  return apiJson<MarketAnalysisListItem[]>(`${BASE}/markets`)
}

export async function getMarketAnalysis(id: string): Promise<MarketAnalysisDetail> {
  return apiJson<MarketAnalysisDetail>(`${BASE}/markets/${id}`)
}
