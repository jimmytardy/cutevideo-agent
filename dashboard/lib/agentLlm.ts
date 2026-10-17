export type LlmProvider = 'gemini' | 'anthropic' | 'claude_cli'
export type LlmTier = 'free' | 'paid'

export interface AgentLlmPreference {
  provider: LlmProvider
  model: string
  tier: LlmTier
}

export interface AgentLlmConfig {
  agents: string[]
  linked_agents: Record<string, string>
  preferences: Record<string, AgentLlmPreference>
  recommendations: Record<string, string>
  has_gemini_key: boolean
  has_anthropic_key: boolean
  has_claude_cli?: boolean
}

const DEFAULT_AGENT_LLM_PREFERENCE: AgentLlmPreference = {
  provider: 'gemini',
  model: 'gemini-2.5-flash-lite',
  tier: 'free',
}

interface ConfigurableAgentInfo {
  label: string
  title: string
  tasks: string[]
}

const CONFIGURABLE_AGENT_INFO: Record<string, ConfigurableAgentInfo> = {
  content_planner_agent: {
    label: 'Planificateur de contenu',
    title: 'Calendrier éditorial',
    tasks: [
      'Choisit les sujets longs et courts à produire chaque jour',
      'Respecte les quotas et créneaux de publication',
      'Évite les sujets déjà traités (historique de la chaîne)',
    ],
  },
  distribution_agent: {
    label: 'Distribution',
    title: 'Publication multi-plateformes',
    tasks: [
      'Planifie les créneaux optimaux YouTube, TikTok, Instagram',
      'Publie avec les titres et descriptions produits par Claude Studio',
      'Orchestre la mise en file d\'attente de publication',
    ],
  },
}

interface AgentLlmGroup {
  id: string
  label: string
  description: string
  agents: string[]
}

const AGENT_LLM_GROUPS: ReadonlyArray<{
  id: string
  label: string
  description: string
  agents: readonly string[]
}> = [
  {
    id: 'planning',
    label: 'Planification éditoriale',
    description: 'Choix quotidien des sujets (la création des vidéos passe par Claude Code CLI).',
    agents: ['content_planner_agent'],
  },
  {
    id: 'distribution',
    label: 'Publication',
    description: 'Planification des créneaux et métadonnées multi-plateformes.',
    agents: ['distribution_agent'],
  },
]

export function groupConfigurableAgents(knownAgents: string[]): AgentLlmGroup[] {
  const known = new Set(knownAgents)
  const groups: AgentLlmGroup[] = []
  const assigned = new Set<string>()

  for (const group of AGENT_LLM_GROUPS) {
    const agents = group.agents.filter((agent) => known.has(agent))
    agents.forEach((agent) => assigned.add(agent))
    if (agents.length > 0) {
      groups.push({ ...group, agents: [...agents] })
    }
  }

  const unassigned = [...known].filter((agent) => !assigned.has(agent)).sort()
  if (unassigned.length > 0) {
    groups.push({
      id: 'other',
      label: 'Autres',
      description: 'Agents configurables non classés.',
      agents: unassigned,
    })
  }

  return groups
}

export function resolvePreferenceAgent(
  agentName: string,
  linkedAgents: Record<string, string>,
): string {
  return linkedAgents[agentName] ?? agentName
}

export function isLinkedAgent(
  agentName: string,
  linkedAgents: Record<string, string>,
): boolean {
  return agentName in linkedAgents
}

const GEMINI_FREE_MODELS = [
  { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash Lite' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
] as const

const GEMINI_PAID_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro Preview' },
] as const

const ANTHROPIC_MODELS = [
  { value: 'claude-opus-5-5', label: 'Claude Opus 5.5' },
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
] as const

// Claude Code CLI : abonnement Claude, aucune clé API requise.
const CLAUDE_CLI_MODELS = [
  { value: 'claude-sonnet-5-5', label: 'Claude Sonnet 5.5' },
  { value: 'claude-opus-5-5', label: 'Claude Opus 5.5' },
  { value: 'claude-haiku-5-5', label: 'Claude Haiku 5.5' },
] as const

const ALL_PROVIDERS: readonly LlmProvider[] = ['gemini', 'anthropic', 'claude_cli']

// Les agents restants ne font que du texte : mêmes règles que agent/core/agent_llm_constraints.py.
export function modelOptionsFor(provider: LlmProvider, tier: LlmTier) {
  if (provider === 'anthropic') {
    return ANTHROPIC_MODELS
  }
  if (provider === 'claude_cli') {
    return CLAUDE_CLI_MODELS
  }
  return tier === 'paid' ? GEMINI_PAID_MODELS : GEMINI_FREE_MODELS
}

export function defaultModel(provider: LlmProvider, tier: LlmTier): string {
  return modelOptionsFor(provider, tier)[0]?.value ?? DEFAULT_AGENT_LLM_PREFERENCE.model
}

export function getAgentInfo(agentName: string): ConfigurableAgentInfo {
  return (
    CONFIGURABLE_AGENT_INFO[agentName] ?? {
      label: agentName,
      title: 'Agent IA',
      tasks: ['Tâches non documentées pour cet agent.'],
    }
  )
}

export function getAgentLabel(agentName: string): string {
  return getAgentInfo(agentName).label
}

export function normalizePreference(pref: AgentLlmPreference): AgentLlmPreference {
  const provider: LlmProvider = ALL_PROVIDERS.includes(pref.provider) ? pref.provider : ALL_PROVIDERS[0]
  const tier: LlmTier = provider === 'anthropic' ? 'paid' : provider === 'claude_cli' ? 'free' : pref.tier === 'paid' ? 'paid' : 'free'
  const validModels: string[] = modelOptionsFor(provider, tier).map((o) => o.value)
  const model = validModels.includes(pref.model) ? pref.model : defaultModel(provider, tier)
  return { provider, tier, model }
}

export function buildPreferencesMap(
  agents: string[],
  saved: Record<string, AgentLlmPreference>,
): Record<string, AgentLlmPreference> {
  const out: Record<string, AgentLlmPreference> = {}
  for (const agent of agents) {
    out[agent] = normalizePreference(saved[agent] ?? DEFAULT_AGENT_LLM_PREFERENCE)
  }
  return out
}
