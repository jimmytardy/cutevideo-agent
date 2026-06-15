export type LlmProvider = 'gemini' | 'anthropic'
export type LlmTier = 'free' | 'paid'
export type AgentTaskKind = 'text' | 'vision' | 'gemini_search'

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
}

export const AGENT_LLM_LINKED_TO: Record<string, string> = {
  revision_agent: 'scenario_agent',
}

export const DEFAULT_AGENT_LLM_PREFERENCE: AgentLlmPreference = {
  provider: 'gemini',
  model: 'gemini-2.5-flash-lite',
  tier: 'free',
}

export interface ConfigurableAgentInfo {
  label: string
  title: string
  tasks: string[]
}

export const CONFIGURABLE_AGENT_INFO: Record<string, ConfigurableAgentInfo> = {
  research_agent: {
    label: 'Chercheur',
    title: 'Collecte documentaire',
    tasks: [
      'Recherche les faits vérifiables sur le sujet de la vidéo',
      'Croise les sources via Gemini et Google Search (Gemini uniquement)',
      'Produit un brief structuré pour le scénariste',
    ],
  },
  scenario_agent: {
    label: 'Scénariste',
    title: 'Structure narrative',
    tasks: [
      'Rédige le script complet segment par segment',
      'Définit les visual beats et les durées',
      'Intègre le brief de recherche et l\'identité éditoriale',
    ],
  },
  revision_agent: {
    label: 'Agent révision',
    title: 'Correction chirurgicale',
    tasks: [
      'Applique les retours du critique sur le scénario',
      'Patche uniquement les passages signalés',
      'Préserve la structure et le ton du script original',
    ],
  },
  critic_agent: {
    label: 'Critique IA',
    title: 'Contrôle qualité',
    tasks: [
      'Analyse la vidéo montée (narration, rythme, cohérence)',
      'Attribue un score et des corrections détaillées',
      'Décide d\'approuver ou de relancer une itération',
    ],
  },
  content_planner_agent: {
    label: 'Planificateur de contenu',
    title: 'Calendrier éditorial',
    tasks: [
      'Choisit les sujets longs et courts à produire chaque jour',
      'Respecte les quotas et créneaux de publication',
      'S\'appuie sur l\'historique et les retours audience',
    ],
  },
  clipper_agent: {
    label: 'Découpeur shorts',
    title: 'Extraction de moments forts',
    tasks: [
      'Identifie les passages les plus accrocheurs du scénario long',
      'Propose 5 à 8 clips de 45 à 90 secondes',
      'Optimise hooks et titres pour la viralité',
    ],
  },
  short_producer_agent: {
    label: 'Producteur shorts',
    title: 'Shorts natifs dérivés',
    tasks: [
      'Génère des mini-scénarios autonomes à partir d\'une vidéo longue',
      'Crée un angle différent avec hook immédiat',
      'Adapte le rythme au format vertical',
    ],
  },
  comments_agent: {
    label: 'Agent commentaires',
    title: 'Engagement communautaire',
    tasks: [
      'Classifie les commentaires YouTube et TikTok',
      'Rédige des réponses pour les cas ambigus',
      'Enrichit le contexte d\'apprentissage de la chaîne',
    ],
  },
  channel_planner_agent: {
    label: 'Planificateur de chaîne',
    title: 'Onboarding éditorial',
    tasks: [
      'Analyse le marché et la concurrence',
      'Suggère des niches et angles distincts',
      'Génère le kit de marque (titres, bios, tags)',
    ],
  },
  distribution_agent: {
    label: 'Distribution',
    title: 'Publication multi-plateformes',
    tasks: [
      'Planifie les créneaux optimaux YouTube, TikTok, Instagram',
      'Rédige titres, descriptions et métadonnées',
      'Orchestre la mise en file d\'attente de publication',
    ],
  },
  scenario_media_gap: {
    label: 'Adaptation écarts média',
    title: 'Scénario sans visuel',
    tasks: [
      'Intervient quand une image IA n\'a pas pu être générée',
      'Réécrit la narration pour ne plus exiger le visuel manquant',
      'Renforce le texte à l\'écran en compensation',
    ],
  },
  validation_brief: {
    label: 'Brief validation média',
    title: 'Critères de curation',
    tasks: [
      'Définit l\'entité sujet et les contraintes visuelles',
      'Liste ce que les images doivent montrer ou éviter',
      'Fixe les seuils de pertinence par segment',
    ],
  },
  source_advisor: {
    label: 'Conseiller sources',
    title: 'Priorisation des banques d\'images',
    tasks: [
      'Recommande quelles sources média privilégier par beat',
      'Adapte la stratégie au type de visuel et à la thématique',
      'Optimise le rapport qualité et licence libre',
    ],
  },
  media_agent_llm: {
    label: 'Scoring média',
    title: 'Pertinence visuelle',
    tasks: [
      'Évalue la pertinence des candidats image ou vidéo via Gemini Vision',
      'Compare les miniatures au brief de validation',
      'Classe les médias par score de relevance (Gemini uniquement)',
    ],
  },
}

export interface AgentLlmGroup {
  id: string
  label: string
  description: string
  agents: string[]
}

export const AGENT_LLM_GROUPS: ReadonlyArray<{
  id: string
  label: string
  description: string
  agents: readonly string[]
}> = [
  {
    id: 'production',
    label: 'Réalisation de la vidéo',
    description: 'Recherche, scénario, révisions et contrôle qualité.',
    agents: ['research_agent', 'scenario_agent', 'critic_agent', 'revision_agent'],
  },
  {
    id: 'media',
    label: 'Médias et visuels',
    description: 'Sourcing, validation et scoring des images et vidéos.',
    agents: ['validation_brief', 'media_agent_llm', 'scenario_media_gap', 'source_advisor'],
  },
  {
    id: 'shorts',
    label: 'Shorts',
    description: 'Découpe et scénarisation des formats courts.',
    agents: ['clipper_agent', 'short_producer_agent'],
  },
  {
    id: 'planning',
    label: 'Planification éditoriale',
    description: 'Calendrier de contenu et onboarding de chaîne.',
    agents: ['content_planner_agent', 'channel_planner_agent'],
  },
  {
    id: 'distribution',
    label: 'Publication',
    description: 'Planification des créneaux et métadonnées multi-plateformes.',
    agents: ['distribution_agent'],
  },
  {
    id: 'engagement',
    label: 'Engagement audience',
    description: 'Modération et réponses aux commentaires.',
    agents: ['comments_agent'],
  },
]

export function groupConfigurableAgents(knownAgents: string[]): AgentLlmGroup[] {
  const known = new Set([...knownAgents, ...Object.keys(AGENT_LLM_LINKED_TO)])
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
  linkedAgents: Record<string, string> = AGENT_LLM_LINKED_TO,
): string {
  return linkedAgents[agentName] ?? agentName
}

export function isLinkedAgent(
  agentName: string,
  linkedAgents: Record<string, string> = AGENT_LLM_LINKED_TO,
): boolean {
  return agentName in linkedAgents
}

export const GEMINI_FREE_MODELS = [
  { value: 'gemini-2.5-flash-lite', label: 'Gemini 2.5 Flash Lite' },
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
] as const

export const GEMINI_PAID_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
  { value: 'gemini-3.1-pro-preview', label: 'Gemini 3.1 Pro Preview' },
] as const

export const GEMINI_VISION_FREE_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
] as const

export const GEMINI_VISION_PAID_MODELS = GEMINI_PAID_MODELS

export const GEMINI_SEARCH_FREE_MODELS = [
  { value: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
  { value: 'gemini-3.5-flash', label: 'Gemini 3.5 Flash' },
] as const

export const GEMINI_SEARCH_PAID_MODELS = GEMINI_PAID_MODELS

export const ANTHROPIC_MODELS = [
  { value: 'claude-opus-4-5', label: 'Claude Opus 4.5' },
  { value: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
] as const

const AGENT_TASK_KIND: Record<string, AgentTaskKind> = {
  media_agent_llm: 'vision',
  research_agent: 'gemini_search',
}

export function agentTaskKind(agentName: string): AgentTaskKind {
  const source = resolvePreferenceAgent(agentName)
  return AGENT_TASK_KIND[source] ?? 'text'
}

export function allowedProvidersFor(agentName: string): readonly LlmProvider[] {
  const kind = agentTaskKind(agentName)
  if (kind === 'vision' || kind === 'gemini_search') {
    return ['gemini']
  }
  return ['gemini', 'anthropic']
}

function geminiModelsForTask(kind: AgentTaskKind, tier: LlmTier) {
  if (kind === 'vision') {
    return tier === 'paid' ? GEMINI_VISION_PAID_MODELS : GEMINI_VISION_FREE_MODELS
  }
  if (kind === 'gemini_search') {
    return tier === 'paid' ? GEMINI_SEARCH_PAID_MODELS : GEMINI_SEARCH_FREE_MODELS
  }
  return tier === 'paid' ? GEMINI_PAID_MODELS : GEMINI_FREE_MODELS
}

export function modelOptionsForAgent(agentName: string, provider: LlmProvider, tier: LlmTier) {
  const kind = agentTaskKind(agentName)
  if (provider === 'anthropic') {
    return kind === 'text' ? ANTHROPIC_MODELS : []
  }
  return geminiModelsForTask(kind, tier)
}

export function modelOptionsFor(provider: LlmProvider, tier: LlmTier) {
  if (provider === 'anthropic') {
    return ANTHROPIC_MODELS
  }
  return tier === 'paid' ? GEMINI_PAID_MODELS : GEMINI_FREE_MODELS
}

export function defaultModelForAgent(
  agentName: string,
  provider: LlmProvider,
  tier: LlmTier,
): string {
  const options = modelOptionsForAgent(agentName, provider, tier)
  return options[0]?.value ?? DEFAULT_AGENT_LLM_PREFERENCE.model
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

export function normalizePreference(
  pref: AgentLlmPreference,
  agentName?: string,
): AgentLlmPreference {
  const sourceAgent = agentName ? resolvePreferenceAgent(agentName) : undefined
  const providers = sourceAgent ? allowedProvidersFor(sourceAgent) : (['gemini', 'anthropic'] as const)
  const provider: LlmProvider = providers.includes(pref.provider as LlmProvider)
    ? pref.provider
    : providers[0]
  const tier: LlmTier = provider === 'anthropic' ? 'paid' : pref.tier === 'paid' ? 'paid' : 'free'
  const options = sourceAgent
    ? modelOptionsForAgent(sourceAgent, provider, tier)
    : modelOptionsFor(provider, tier)
  const validModels = options.map((o) => o.value)
  const model = validModels.includes(pref.model as (typeof validModels)[number])
    ? pref.model
    : sourceAgent
      ? defaultModelForAgent(sourceAgent, provider, tier)
      : options[0].value
  return { provider, tier, model }
}

export function buildPreferencesMap(
  agents: string[],
  saved: Record<string, AgentLlmPreference>,
): Record<string, AgentLlmPreference> {
  const out: Record<string, AgentLlmPreference> = {}
  for (const agent of agents) {
    out[agent] = normalizePreference(saved[agent] ?? DEFAULT_AGENT_LLM_PREFERENCE, agent)
  }
  return out
}
