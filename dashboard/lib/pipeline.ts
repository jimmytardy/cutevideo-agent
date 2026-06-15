import type { AgentRun, CriticReport } from '@/lib/api'

export interface PipelineSelection {
  step: string
  iteration?: number
}

export type AgentStatus = 'pending' | 'running' | 'success' | 'failed' | 'stopped' | 'planned'

export type IterationRowState = 'planned' | 'active' | 'done' | 'failed'

export const AGENT_LABELS: Record<string, string> = {
  research_agent: 'Chercheur',
  scenario_agent: 'Scénariste',
  revision_agent: 'Agent Révision',
  media_agent: 'Chercheur Média',
  narrator_agent: 'Narrateur Voix',
  editor_agent: 'Monteur Vidéo',
  subtitle_agent: 'Sous-titreur',
  critic_agent: 'Critique IA',
  clipper_agent: 'Découpeur Shorts',
  short_editor_agent: 'Éditeur Shorts',
}

export const ITERATION_AGENT_KEYS = [
  'revision_agent',
  'media_agent',
  'narrator_agent',
  'editor_agent',
  'subtitle_agent',
  'critic_agent',
] as const

export const ITERATION_1_AGENT_KEYS = [
  'media_agent',
  'narrator_agent',
  'editor_agent',
  'subtitle_agent',
  'critic_agent',
] as const

export const DELETION_SUMMARY: Record<string, string[]> = {
  research_agent: ['Brief recherche', 'Scénarios', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  scenario_agent: ['Scénarios (visual beats)', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  revision_agent: ['Scénario révisé (visual beats)', 'Médias', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  media_agent: ['Médias (par beat + bibliothèque)', 'Fichiers audio', 'Vidéos', 'Rapports critiques'],
  narrator_agent: ['Fichiers audio', 'Vidéos', 'Rapports critiques'],
  editor_agent: ['Vidéos', 'Rapports critiques'],
  subtitle_agent: ['Vidéos', 'Rapports critiques'],
  critic_agent: ['Rapports critiques', 'Vidéos courtes'],
  clipper_agent: ['Vidéos courtes'],
  short_editor_agent: ['Vidéos courtes'],
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

export function getActiveCriticIteration(
  criticReports: CriticReport[],
  projectStatus: string,
): number {
  if (criticReports.length === 0) {
    return projectStatus === 'running' ? 1 : 0
  }
  const last = criticReports[criticReports.length - 1]
  const lastIter = reportIteration(last, criticReports.length)
  if (last.decision === 'approve') {
    return lastIter
  }
  if (projectStatus === 'running') {
    return lastIter + 1
  }
  return lastIter
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
): IterationRowState {
  const report = criticReports.find((r, idx) => reportIteration(r, idx + 1) === iteration)
  if (report) {
    const hasFailed = agentRuns.some(
      (r) => r.iteration === iteration && r.status === 'failed',
    )
    return hasFailed ? 'failed' : 'done'
  }

  const activeIter = getActiveCriticIteration(criticReports, projectStatus)

  if (activeIter === 0) {
    return 'planned'
  }

  if (iteration === activeIter && projectStatus === 'running') {
    return 'active'
  }

  if (iteration < activeIter) {
    return projectStatus === 'running' ? 'active' : 'failed'
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
): AgentStatus {
  if (rowState === 'planned') return 'planned'

  const run = iteration != null
    ? getAgentRunForStep(agentRuns, agentName, iteration)
    : getAgentRunForStep(agentRuns, agentName)

  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'

  if (projectStatus === 'running' && rowState === 'active') {
    const redis = redisStatuses?.[agentName]
    if (redis === 'running' || redis === 'stopped' || redis === 'failed') {
      return redis as AgentStatus
    }
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
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'research_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (projectStatus === 'running') {
    const redis = redisStatuses?.research_agent
    if (redis === 'running' || redis === 'stopped' || redis === 'failed') {
      return redis as AgentStatus
    }
  }
  return 'pending'
}

export function deriveScenarioStatus(
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, 'scenario_agent')
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'
  if (run?.status === 'running') return 'running'
  if (projectStatus === 'running') {
    const redis = redisStatuses?.scenario_agent
    if (redis === 'running' || redis === 'stopped' || redis === 'failed') {
      return redis as AgentStatus
    }
  }
  return 'pending'
}

export function derivePostProdStatus(
  agentName: string,
  agentRuns: AgentRun[],
  redisStatuses: Record<string, string> | undefined,
  projectStatus: string,
  criticApproved: boolean,
): AgentStatus {
  const run = getAgentRunForStep(agentRuns, agentName)
  if (run?.status === 'failed') return 'failed'
  if (run?.status === 'stopped') return 'stopped'
  if (run?.status === 'success') return 'success'

  if (projectStatus === 'running') {
    const redis = redisStatuses?.[agentName]
    if (redis === 'running' || redis === 'stopped' || redis === 'failed') {
      return redis as AgentStatus
    }
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
