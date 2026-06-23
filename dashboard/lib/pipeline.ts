import type { AgentProgressItem, AgentRun, CriticReport, PipelineProgressResponse } from '@/lib/api'

export interface PipelineSelection {
  step: string
  iteration?: number
}

export type AgentStatus = 'pending' | 'running' | 'success' | 'failed' | 'stopped' | 'planned'

export type IterationRowState = 'planned' | 'active' | 'done' | 'failed' | 'stopped'

export interface ResumeTarget {
  step: string
  iteration?: number
  label: string
}

export interface PipelineKickoff {
  fromStep: string
  startedAt: number
}

const KICKOFF_OVERRIDABLE_STATUSES = new Set(['pending', 'queued', 'stopped', 'failed', 'approved'])

export function getEffectiveProjectStatus(
  projectStatus: string,
  kickoff: PipelineKickoff | null | undefined,
): string {
  if (kickoff && KICKOFF_OVERRIDABLE_STATUSES.has(projectStatus)) {
    return 'running'
  }
  return projectStatus
}

export function isPipelineInFlight(
  projectStatus: string,
  kickoff: PipelineKickoff | null | undefined,
): boolean {
  return projectStatus === 'running' || projectStatus === 'queued' || projectStatus === 'pending' || Boolean(kickoff)
}

function shouldCheckRedis(
  projectStatus: string,
  kickoff: PipelineKickoff | null | undefined,
): boolean {
  return projectStatus === 'running' || projectStatus === 'queued' || projectStatus === 'pending' || Boolean(kickoff)
}

function resolveRedisStatus(
  redisStatuses: Record<string, string> | undefined,
  agentName: string,
): AgentStatus | null {
  const redis = redisStatuses?.[agentName]
  if (redis === 'running' || redis === 'stopped' || redis === 'failed') {
    return redis as AgentStatus
  }
  return null
}

function isKickoffAgent(
  agentName: string,
  kickoff: PipelineKickoff | null | undefined,
  run: AgentRun | undefined,
): boolean {
  return kickoff?.fromStep === agentName && run?.status !== 'running'
}

export const AGENT_LABELS: Record<string, string> = {
  research_agent: 'Chercheur',
  outline_agent: 'Architecte éditorial',
  scenario_agent: 'Scénariste',
  fact_checker_agent: 'Vérificateur factuel',
  hook_optimizer_agent: 'Optimiseur accroche',
  revision_agent: 'Agent Révision',
  narrator_agent: 'Narrateur Voix',
  art_director_agent: 'Directeur artistique',
  beat_planner_agent: 'Planificateur segment',
  diagram_specialist_agent: 'Spécialiste diagrammes',
  media_agent: 'Chercheur Média',
  montage_planner_agent: 'Planificateur montage',
  editor_agent: 'Monteur Vidéo',
  subtitle_agent: 'Sous-titreur',
  critic_agent: 'Critique IA',
  metadata_agent: 'Métadonnées SEO',
  thumbnail_agent: 'Miniature',
  clipper_agent: 'Découpeur Shorts',
  short_editor_agent: 'Éditeur Shorts',
}

export const PREPARATION_AGENT_KEYS = [
  'research_agent',
  'outline_agent',
  'scenario_agent',
  'fact_checker_agent',
  'hook_optimizer_agent',
] as const

export const ITERATION_AGENT_KEYS = [
  'revision_agent',
  'narrator_agent',
  'art_director_agent',
  'beat_planner_agent',
  'diagram_specialist_agent',
  'media_agent',
  'montage_planner_agent',
  'editor_agent',
  'subtitle_agent',
  'critic_agent',
] as const

export const ITERATION_1_AGENT_KEYS = [
  'narrator_agent',
  'art_director_agent',
  'beat_planner_agent',
  'diagram_specialist_agent',
  'media_agent',
  'montage_planner_agent',
  'editor_agent',
  'subtitle_agent',
  'critic_agent',
] as const

export const DELETION_SUMMARY: Record<string, string[]> = {
  research_agent: ['Brief recherche', 'Plan éditorial', 'Scénarios', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  outline_agent: ['Plan éditorial', 'Scénarios', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  fact_checker_agent: ['Scénarios (si corrections)', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  scenario_agent: ['Scénarios (visual beats)', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  hook_optimizer_agent: [
    'Accroche optimisée (segment 1)',
    'Médias (beats hook)',
    'Fichiers audio',
    'Plan de montage',
    'Vidéos',
    'Rapports critiques',
  ],
  revision_agent: ['Scénario révisé (visual beats)', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  narrator_agent: ['Fichiers audio', 'Visual beats', 'Médias', 'Plan de montage', 'Vidéos', 'Rapports critiques'],
  art_director_agent: ['Direction visuelle', 'Médias', 'Vidéos', 'Rapports critiques'],
  beat_planner_agent: ['Visual beats', 'Médias', 'Plan de montage', 'Vidéos', 'Rapports critiques'],
  diagram_specialist_agent: ['Schémas diagramme', 'Médias', 'Plan de montage', 'Vidéos', 'Rapports critiques'],
  media_agent: ['Médias (par beat + bibliothèque)', 'Plan de montage', 'Vidéos', 'Rapports critiques'],
  montage_planner_agent: ['Plan de montage', 'Vidéos', 'Rapports critiques'],
  editor_agent: ['Vidéos', 'Rapports critiques'],
  subtitle_agent: ['Vidéos', 'Rapports critiques'],
  critic_agent: ['Rapports critiques', 'Vidéos courtes'],
  clipper_agent: ['Vidéos courtes'],
  short_editor_agent: ['Vidéos courtes'],
  metadata_agent: ['Métadonnées YouTube'],
  thumbnail_agent: ['Concepts miniature'],
}

export function effectiveMaxIterations(maxIterations: number, isShort: boolean): number {
  return isShort ? Math.min(maxIterations, 2) : maxIterations
}

export function selectionKey(sel: PipelineSelection): string {
  return sel.iteration != null ? `${sel.step}:${sel.iteration}` : sel.step
}

export function matchesSelection(sel: PipelineSelection, step: string, iteration?: number): boolean {
  if (sel.step !== step) return false
  if (sel.iteration == null) return iteration == null
  return sel.iteration === iteration
}

function reportIteration(report: CriticReport, fallback: number): number {
  return report.iteration ?? fallback
}

const PIPELINE_ITERATION_AGENTS = new Set<string>([
  ...ITERATION_AGENT_KEYS,
  ...ITERATION_1_AGENT_KEYS,
])

function isPipelineIterationAgent(agentName: string | null): boolean {
  return agentName != null && PIPELINE_ITERATION_AGENTS.has(agentName)
}

function getHighestIterationFromRuns(agentRuns: AgentRun[]): number {
  const iterations = agentRuns
    .filter((r) => isPipelineIterationAgent(r.agent_name))
    .map((r) => r.iteration)
  if (iterations.length === 0) return 0
  return Math.max(...iterations)
}

function iterationHasAgentRuns(agentRuns: AgentRun[], iteration: number): boolean {
  return agentRuns.some(
    (r) => r.iteration === iteration && isPipelineIterationAgent(r.agent_name),
  )
}

export function getActiveCriticIteration(
  criticReports: CriticReport[],
  projectStatus: string,
  agentRuns: AgentRun[] = [],
  kickoff?: PipelineKickoff | null,
): number {
  const effectiveStatus = getEffectiveProjectStatus(projectStatus, kickoff)
  const runsIter = getHighestIterationFromRuns(agentRuns)

  if (criticReports.length === 0) {
    if (effectiveStatus === 'running') {
      return Math.max(1, runsIter)
    }
    return runsIter
  }

  const last = criticReports[criticReports.length - 1]
  const lastIter = reportIteration(last, criticReports.length)
  if (last.decision === 'approve') {
    return lastIter
  }
  // Rapport rejeté : les corrections s'appliquent à l'itération suivante
  const nextIter = lastIter + 1
  return Math.max(nextIter, runsIter)
}

export function isCriticLoopApproved(criticReports: CriticReport[]): boolean {
  if (criticReports.length === 0) return false
  const last = criticReports[criticReports.length - 1]
  return last.decision === 'approve'
}

export function getIterationRowState(
  iteration: number,
  criticReports: CriticReport[],
  projectStatus: string,
  agentRuns: AgentRun[],
  kickoff?: PipelineKickoff | null,
): IterationRowState {
  const effectiveStatus = getEffectiveProjectStatus(projectStatus, kickoff)
  const report = criticReports.find((r, idx) => reportIteration(r, idx + 1) === iteration)
  if (report) {
    const hasFailed = agentRuns.some(
      (r) => r.iteration === iteration && r.status === 'failed',
    )
    return hasFailed ? 'failed' : 'done'
  }

  const activeIter = getActiveCriticIteration(criticReports, projectStatus, agentRuns, kickoff)

  if (activeIter === 0) {
    return 'planned'
  }

  if (iteration === activeIter) {
    if (effectiveStatus === 'running' || projectStatus === 'pending') return 'active'
    if (projectStatus === 'stopped') return 'stopped'
    if (iterationHasAgentRuns(agentRuns, iteration)) return 'failed'
    return 'planned'
  }

  if (iteration < activeIter) {
    return effectiveStatus === 'running' ? 'active' : projectStatus === 'stopped' ? 'stopped' : 'failed'
  }

  return 'planned'
}

export function getAgentRunForStep(
  agentRuns: AgentRun[],
  agentName: string,
  iteration?: number,
): AgentRun | undefined {
  const matches = agentRuns.filter((r) => r.agent_name === agentName)
  if (iteration != null) {
    return matches
      .filter((r) => r.iteration === iteration)
      .sort((a, b) => (b.started_at ?? '').localeCompare(a.started_at ?? ''))[0]
  }
  return matches.sort((a, b) => b.iteration - a.iteration)[0]
}

export function deriveAgentStatus(
  agentName: string,
  iteration: number | undefined,
  rowState: IterationRowState,
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  if (rowState === 'planned') return 'planned'

  const run = iteration != null
    ? getAgentRunForStep(agentRuns, agentName, iteration)
    : getAgentRunForStep(agentRuns, agentName)

  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'

  if (isKickoffAgent(agentName, kickoff, run)) return 'running'

  if (shouldCheckRedis(projectStatus, kickoff) && rowState === 'active') {
    const redis = resolveRedisStatus(redisStatuses, agentName)
    if (redis) return redis
  }

  if (projectStatus === 'stopped' && rowState === 'stopped') {
    const redis = resolveRedisStatus(redisStatuses, agentName)
    if (redis === 'stopped') return 'stopped'
    if (redis === 'running') return 'running'
  }

  if (rowState === 'done') {
    if (agentName === 'revision_agent' && iteration != null && iteration <= 1) {
      return 'planned'
    }
    return 'success'
  }

  return 'pending'
}

export function deriveResearchStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'research_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (isKickoffAgent('research_agent', kickoff, run)) return 'running'
  if (shouldCheckRedis(projectStatus, kickoff)) {
    const redis = resolveRedisStatus(redisStatuses, 'research_agent')
    if (redis) return redis
  }
  return 'pending'
}

export function deriveOutlineStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'outline_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (isKickoffAgent('outline_agent', kickoff, run)) return 'running'
  if (shouldCheckRedis(projectStatus, kickoff)) {
    const redis = resolveRedisStatus(redisStatuses, 'outline_agent')
    if (redis) return redis
  }
  return 'pending'
}

export function deriveFactCheckerStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  scenarioStatus: AgentStatus,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'fact_checker_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (isKickoffAgent('fact_checker_agent', kickoff, run)) return 'running'
  if (shouldCheckRedis(projectStatus, kickoff) && scenarioStatus === 'success') {
    const redis = resolveRedisStatus(redisStatuses, 'fact_checker_agent')
    if (redis) return redis
  }
  if (scenarioStatus === 'success' || scenarioStatus === 'running') return 'pending'
  return 'planned'
}

export function deriveScenarioStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'scenario_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (isKickoffAgent('scenario_agent', kickoff, run)) return 'running'
  if (shouldCheckRedis(projectStatus, kickoff)) {
    const redis = resolveRedisStatus(redisStatuses, 'scenario_agent')
    if (redis) return redis
  }
  return 'pending'
}

export function deriveHookOptimizerStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  scenarioStatus: AgentStatus,
  kickoff?: PipelineKickoff | null,
  isShort?: boolean,
): AgentStatus {
  if (isShort) return 'planned'
  const run = getAgentRunForStep(agentRuns, 'hook_optimizer_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (isKickoffAgent('hook_optimizer_agent', kickoff, run)) return 'running'
  if (shouldCheckRedis(projectStatus, kickoff) && scenarioStatus === 'success') {
    const redis = resolveRedisStatus(redisStatuses, 'hook_optimizer_agent')
    if (redis) return redis
  }
  if (scenarioStatus === 'success' && run?.status === 'success') return 'success'
  if (scenarioStatus === 'success' || scenarioStatus === 'running') return 'pending'
  return 'planned'
}

export function derivePostProdStatus(
  agentName: string,
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  criticApproved: boolean,
  kickoff?: PipelineKickoff | null,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, agentName)
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'

  if (isKickoffAgent(agentName, kickoff, run)) return 'running'

  if (shouldCheckRedis(projectStatus, kickoff)) {
    const redis = resolveRedisStatus(redisStatuses, agentName)
    if (redis) return redis
  }

  if (!criticApproved) return 'planned'
  return 'pending'
}

export function statusDotColor(status: AgentStatus): string {
  if (status === 'success') return '#22c55e'
  if (status === 'running') return '#3b82f6'
  if (status === 'failed') return '#ef4444'
  if (status === 'stopped') return '#f59e0b'
  if (status === 'planned') return '#d1d5db'
  return '#9ca3af'
}

export function getCriticReportForIteration(
  criticReports: CriticReport[],
  iteration: number,
): CriticReport | undefined {
  return criticReports.find((r, idx) => reportIteration(r, idx + 1) === iteration)
}

function isAgentStepComplete(
  agentRuns: AgentRun[],
  step: string,
  iteration?: number,
): boolean {
  return getAgentRunForStep(agentRuns, step, iteration)?.status === 'success'
}

/** Prochaine étape à exécuter après un arrêt ou un échec partiel. */
export function getResumeStep(
  agentRuns: AgentRun[],
  projectStatus: string,
  criticReports: CriticReport[],
  isShort: boolean,
  kickoff?: PipelineKickoff | null,
  postProductionAgents?: string[],
): ResumeTarget | null {
  const effectiveStatus = getEffectiveProjectStatus(projectStatus, kickoff)
  if (effectiveStatus === 'approved' || effectiveStatus === 'running') return null
  if (projectStatus === 'pending') return null

  if (!isAgentStepComplete(agentRuns, 'research_agent')) {
    return { step: 'research_agent', label: AGENT_LABELS.research_agent }
  }
  if (!isAgentStepComplete(agentRuns, 'outline_agent')) {
    return { step: 'outline_agent', label: AGENT_LABELS.outline_agent }
  }
  if (!isAgentStepComplete(agentRuns, 'scenario_agent')) {
    return { step: 'scenario_agent', label: AGENT_LABELS.scenario_agent }
  }
  if (!isAgentStepComplete(agentRuns, 'fact_checker_agent')) {
    return { step: 'fact_checker_agent', label: AGENT_LABELS.fact_checker_agent }
  }
  if (
    !isShort
    && !isAgentStepComplete(agentRuns, 'hook_optimizer_agent')
    && !isAgentStepComplete(agentRuns, 'media_agent', 1)
  ) {
    return { step: 'hook_optimizer_agent', label: AGENT_LABELS.hook_optimizer_agent }
  }

  const activeIter = Math.max(1, getActiveCriticIteration(criticReports, projectStatus, agentRuns, kickoff))
  const iterationSteps = activeIter === 1 ? ITERATION_1_AGENT_KEYS : ITERATION_AGENT_KEYS

  for (const step of iterationSteps) {
    if (!isAgentStepComplete(agentRuns, step, activeIter)) {
      return { step, iteration: activeIter, label: AGENT_LABELS[step] ?? step }
    }
  }

  if (isCriticLoopApproved(criticReports)) {
    const postSteps = postProductionAgents
      ?? (isShort
        ? ['metadata_agent', 'short_editor_agent']
        : ['metadata_agent', 'thumbnail_agent', 'clipper_agent', 'short_editor_agent'])
    for (const step of postSteps) {
      if (!isAgentStepComplete(agentRuns, step)) {
        return { step, label: AGENT_LABELS[step] ?? step }
      }
    }
  }

  return null
}

export function isResumeTarget(
  step: string,
  iteration: number | undefined,
  resume: ResumeTarget | null,
): boolean {
  if (!resume || resume.step !== step) return false
  if (resume.iteration != null) return iteration === resume.iteration
  return iteration == null
}

export function pickAgentProgress(
  progress: PipelineProgressResponse | undefined,
  agent: string,
  iteration?: number,
): AgentProgressItem | undefined {
  if (!progress) return undefined
  if (iteration != null) {
    return progress.iterations[String(iteration)]?.[agent]
  }
  if (progress.preparation[agent]) {
    return progress.preparation[agent]
  }
  return progress.post_production[agent]
}
