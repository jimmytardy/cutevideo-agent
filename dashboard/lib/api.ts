const BASE = '/api/v1'

export interface Channel {
  id: string
  slug: string
  name: string
  theme_category: string
  niche_prompt: string | null
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

const fetcher = (url: string) => fetch(url).then((r) => r.json())

export { fetcher }

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
