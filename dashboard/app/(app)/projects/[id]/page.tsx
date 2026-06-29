'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import useSWR, { useSWRConfig } from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Tooltip from '@mui/material/Tooltip'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import StopIcon from '@mui/icons-material/Stop'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import AddIcon from '@mui/icons-material/Add'
import DeleteIcon from '@mui/icons-material/Delete'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import { PageContainer, PageHeader, PageSection, LoadingState, useConfirmDialog } from '@/components/layout'
import { projectStatusLabel, projectStatusColor } from '@/lib/status'
import PipelineVisualizer from '@/components/PipelineVisualizer'
import AgentOutputPanel from '@/components/AgentOutputPanel'
import FinalPreviewSection from '@/components/FinalPreviewSection'
import MediaValidationPanel from '@/components/MediaValidationPanel'
import {
  fetcher,
  pipelinePlanUrl,
  stopPipeline,
  restartPipeline,
  dequeueProject,
  runFromStep,
  restartFromCriticIteration,
  updateProjectMaxIterations,
  clearProjectMaxIterations,
  deleteProject,
  type Project,
  type ProjectCost,
  type AgentRun,
  type CriticReport,
  type Scenario,
  type PipelinePlanResponse,
  type AuthUser,
} from '@/lib/api'
import { selectionKey, getResumeStep, getEffectiveProjectStatus, type PipelineSelection, type PipelineKickoff } from '@/lib/pipeline'

interface Props {
  params: { id: string }
}

export default function ProjectDetailPage({ params }: Props) {
  const { id } = params
  const router = useRouter()
  const { confirm, dialog } = useConfirmDialog()
  const [tab, setTab] = useState(0)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [maxIterInput, setMaxIterInput] = useState<string>('')
  const [maxIterSaving, setMaxIterSaving] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<PipelineSelection | null>(null)
  const [restartingReportId, setRestartingReportId] = useState<string | null>(null)
  const [pipelineKickoff, setPipelineKickoff] = useState<PipelineKickoff | null>(null)
  const { mutate: swrMutate } = useSWRConfig()

  const { data: project, isLoading, error, mutate: mutateProject } = useSWR<Project>(
    `/api/v1/projects/${id}`,
    fetcher,
    {
      refreshInterval: (data) =>
        pipelineKickoff ? 1000 : data?.status === 'queued' ? 5000 : 3000,
    },
  )
  const { data: agentRuns } = useSWR<AgentRun[]>(
    `/api/v1/agents/runs/${id}`,
    fetcher,
    {
      refreshInterval: ['running', 'queued', 'stopped', 'pending'].includes(project?.status ?? '') || pipelineKickoff
        ? 3000
        : 0,
    },
  )
  const { data: criticReports } = useSWR<CriticReport[]>(
    `/api/v1/projects/${id}/critic-reports`,
    fetcher,
    { refreshInterval: project?.status === 'running' || pipelineKickoff ? 5000 : 0 },
  )
  const { data: scenario } = useSWR<Scenario | null>(
    `/api/v1/projects/${id}/scenario`,
    fetcher,
    { refreshInterval: project?.status === 'running' || pipelineKickoff ? 5000 : 0 },
  )
  // Plan du pipeline : quels agents tournent réellement pour ce type de vidéo.
  const { data: pipelinePlan } = useSWR<PipelinePlanResponse>(
    pipelinePlanUrl(id),
    fetcher,
  )
  const { data: me } = useSWR<AuthUser>('/api/v1/auth/me', fetcher)
  const { data: projectCost } = useSWR<ProjectCost>(
    `/api/v1/projects/${id}/cost`,
    fetcher,
    {
      refreshInterval: (data) => {
        if (pipelineKickoff) return 5000
        return ['running', 'queued'].includes(project?.status ?? '') ? 5000 : 0
      },
    },
  )

  useEffect(() => {
    if (!pipelineKickoff || !project) return
    if (project.status === 'running') {
      setPipelineKickoff(null)
      return
    }
    if (project.status === 'failed' || project.status === 'stopped') {
      setPipelineKickoff(null)
    }
  }, [project?.status, pipelineKickoff, project])

  if (isLoading) return <LoadingState variant="page" />
  if (error || !project) return <PageContainer><Alert severity="error">Projet introuvable</Alert></PageContainer>

  const effectiveProjectStatus = getEffectiveProjectStatus(project.status, pipelineKickoff)
  const isRunning = effectiveProjectStatus === 'running'
  const isQueued = project.status === 'queued'
  const failedRuns = agentRuns?.filter((r) => r.status === 'failed' && r.error) ?? []
  const canRestart = ['failed', 'stopped', 'approved', 'pending'].includes(project.status)
  // Repli sur le format projet tant que le plan n'est pas chargé.
  const isShort = pipelinePlan?.is_short
    ?? (project.config?.format === 'short_standalone' || project.config?.format === 'short')
  const resumeTarget = getResumeStep(
    agentRuns ?? [],
    project.status,
    criticReports ?? [],
    isShort,
    pipelineKickoff,
    pipelinePlan?.post_production,
  )

  const beginPipelineKickoff = (fromStep: string) => {
    setPipelineKickoff({ fromStep, startedAt: Date.now() })
  }

  const revalidatePipelineData = async () => {
    await Promise.all([
      swrMutate(`/api/v1/projects/${id}/critic-reports`),
      swrMutate(`/api/v1/projects/${id}/scenario`),
      swrMutate(`/api/v1/projects/${id}/media-assets`),
      swrMutate(`/api/v1/projects/${id}/audio`),
      swrMutate(`/api/v1/projects/${id}/videos`),
      swrMutate(`/api/v1/agents/runs/${id}`),
      swrMutate(`/api/v1/agents/status/${id}`),
    ])
  }

  const configuredMax = project.config?.max_critic_iterations as number | undefined
  const maxIterationsUnlimited = pipelinePlan?.max_iterations_unlimited ?? false
  const displayMaxIter = pipelinePlan?.max_iterations ?? 5
  const iterCount = criticReports?.length ?? 0
  const numericMaxIter = configuredMax ?? (
    maxIterationsUnlimited ? Math.max(displayMaxIter, iterCount) : displayMaxIter
  )
  const maxIterLabel = configuredMax !== undefined
    ? String(configuredMax)
    : maxIterationsUnlimited
      ? '5 (illimité)'
      : String(displayMaxIter)

  const handleDequeue = async () => {
    setActionError(null)
    setActionLoading(true)
    try {
      await dequeueProject(id)
      await mutateProject()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
    }
  }

  const handleStop = async () => {
    setActionError(null)
    setActionLoading(true)
    try {
      await stopPipeline(id)
      await mutateProject()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
    }
  }

  const handleRestart = async () => {
    setActionError(null)
    setActionLoading(true)
    beginPipelineKickoff('research_agent')
    try {
      await mutateProject({ ...project, status: 'queued' }, { revalidate: false })
      await restartPipeline(id)
      await mutateProject()
    } catch (e) {
      setPipelineKickoff(null)
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
    }
  }

  const handleSaveMaxIter = async () => {
    const val = parseInt(maxIterInput, 10)
    if (!Number.isFinite(val) || val < 1) return
    setMaxIterSaving(true)
    try {
      await updateProjectMaxIterations(id, val)
      await mutateProject()
      await swrMutate(pipelinePlanUrl(id))
      setMaxIterInput('')
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur mise à jour')
    } finally {
      setMaxIterSaving(false)
    }
  }

  const handleClearMaxIter = async () => {
    setMaxIterSaving(true)
    try {
      await clearProjectMaxIterations(id)
      await mutateProject()
      await swrMutate(pipelinePlanUrl(id))
      setMaxIterInput('')
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur mise à jour')
    } finally {
      setMaxIterSaving(false)
    }
  }

  const handleRunFrom = async (step: string, _iteration?: number) => {
    setActionError(null)
    setActionLoading(true)
    beginPipelineKickoff(step)
    try {
      await mutateProject({ ...project, status: 'queued' }, { revalidate: false })
      await runFromStep(id, step)
      try {
        await mutateProject()
        await revalidatePipelineData()
      } catch (revalidateError) {
        console.warn('Revalidation pipeline après relancement :', revalidateError)
      }
    } catch (e) {
      setPipelineKickoff(null)
      const message = e instanceof Error ? e.message : 'Erreur inconnue'
      setActionError(message)
      throw e
    } finally {
      setActionLoading(false)
    }
  }

  const handleResume = async () => {
    if (!resumeTarget) return
    await handleRunFrom(resumeTarget.step)
  }

  const handleRestartFromCritic = async (reportId: string) => {
    setActionError(null)
    setActionLoading(true)
    setRestartingReportId(reportId)
    try {
      const result = await restartFromCriticIteration(id, reportId)
      beginPipelineKickoff(result.critic_start_from)
      await mutateProject({ ...project, status: 'queued' }, { revalidate: false })
      await mutateProject()
      await revalidatePipelineData()
    } catch (e) {
      setPipelineKickoff(null)
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
      setRestartingReportId(null)
    }
  }

  const handleSelectAgent = (sel: PipelineSelection | null) => {
    if (!sel) {
      setSelectedAgent(null)
      return
    }
    setSelectedAgent((prev) =>
      prev && selectionKey(prev) === selectionKey(sel) ? null : sel,
    )
  }

  const handleForceIteration = async () => {
    setActionError(null)
    setActionLoading(true)
    beginPipelineKickoff('research_agent')
    try {
      await mutateProject({ ...project, status: 'queued' }, { revalidate: false })
      await updateProjectMaxIterations(id, numericMaxIter + 1)
      await mutateProject()
      await restartPipeline(id)
      await mutateProject()
    } catch (e) {
      setPipelineKickoff(null)
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    const ok = await confirm({
      title: 'Supprimer le projet',
      message: `Supprimer « ${project.title || project.theme} » ? Cette action est irréversible.`,
      confirmLabel: 'Supprimer',
      confirmColor: 'error',
    })
    if (!ok) return
    setActionError(null)
    setActionLoading(true)
    try {
      await deleteProject(id)
      router.push('/projects')
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur suppression')
      setActionLoading(false)
    }
  }

  const statusChipColor = projectStatusColor(effectiveProjectStatus)

  const headerActions = (
    <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1 }}>
      {isQueued && (
        <Button
          variant="outlined"
          color="warning"
          size="small"
          startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <StopIcon />}
          onClick={handleDequeue}
          disabled={actionLoading}
        >
          Retirer de la file
        </Button>
      )}
      {isRunning && (
        <Button
          variant="contained"
          color="error"
          size="small"
          startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <StopIcon />}
          onClick={handleStop}
          disabled={actionLoading}
        >
          Arrêter
        </Button>
      )}
      {resumeTarget && ['stopped', 'failed'].includes(project.status) && (
        <Button
          variant="contained"
          size="small"
          startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
          onClick={handleResume}
          disabled={actionLoading}
        >
          Reprendre
        </Button>
      )}
      {canRestart && (
        <Button
          variant="outlined"
          size="small"
          startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <ReplayIcon />}
          onClick={handleRestart}
          disabled={actionLoading}
        >
          Relancer
        </Button>
      )}
      {!isRunning && !isQueued && (
        <Button
          variant="outlined"
          color="error"
          size="small"
          startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <DeleteIcon />}
          onClick={handleDelete}
          disabled={actionLoading}
        >
          Supprimer
        </Button>
      )}
    </Stack>
  )

  return (
    <PageContainer>
      <PageHeader
        title={project.title || project.theme}
        description={[
          project.channel_name && `Chaîne : ${project.channel_name}`,
          `Sujet : ${project.theme}`,
          project.target_duration_seconds && `${Math.round(project.target_duration_seconds / 60)} min`,
        ]
          .filter(Boolean)
          .join(' · ')}
        breadcrumbs={[
          { label: 'Projets', href: '/projects' },
          { label: project.title || project.theme },
        ]}
        actions={
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Chip
              label={projectStatusLabel(effectiveProjectStatus)}
              color={statusChipColor === 'default' ? undefined : statusChipColor}
              size="small"
            />
            {headerActions}
          </Box>
        }
      />

      {isQueued && project.queue_position != null && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Position <strong>#{project.queue_position}</strong>
          {project.queue_length != null && (
            <>
              {' '}
              sur <strong>{project.queue_length}</strong> projet(s) en file
            </>
          )}
          {project.error_message && <> — {project.error_message}</>}
        </Alert>
      )}

      <Stack direction="row" spacing={1} sx={{ mb: 2, flexWrap: 'wrap', gap: 1 }}>
        {canRestart && (
          <Tooltip title={`Passe de ${numericMaxIter} à ${numericMaxIter + 1} itérations max et relance`}>
            <Button
              variant="outlined"
              color="secondary"
              size="small"
              startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <AddIcon />}
              onClick={handleForceIteration}
              disabled={actionLoading}
            >
              Forcer +1 itération
            </Button>
          </Tooltip>
        )}
      </Stack>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
        <Typography variant="body2" color="text.secondary">
          Itérations : <strong>{iterCount}</strong> réalisées · max actuel : <strong>{maxIterLabel}</strong>
        </Typography>
        <TextField
          size="small"
          type="number"
          placeholder={configuredMax !== undefined ? String(configuredMax) : String(displayMaxIter)}
          value={maxIterInput}
          onChange={(e) => setMaxIterInput(e.target.value)}
          inputProps={{ min: 1, ...(me?.is_admin ? {} : { max: displayMaxIter }) }}
          sx={{ width: 90 }}
        />
        <Button variant="outlined" size="small" onClick={handleSaveMaxIter} disabled={maxIterSaving || !maxIterInput}>
          {maxIterSaving ? <CircularProgress size={14} /> : 'Modifier'}
        </Button>
        {me?.is_admin && (
          <Button
            variant="text"
            size="small"
            onClick={handleClearMaxIter}
            disabled={maxIterSaving || (configuredMax === undefined && maxIterationsUnlimited)}
          >
            Illimité
          </Button>
        )}
      </Box>

      {projectCost && (
        <Box sx={{ mb: 3 }}>
        <PageSection title="Coût LLM">
          <Stack spacing={1}>
            <Typography variant="body2">
              Coût estimé : <strong>${projectCost.total_usd.toFixed(4)}</strong>
              {' / '}
              plafond ${projectCost.cap_usd.toFixed(2)}
              {' · '}
              Itérations : <strong>{projectCost.iterations_used}</strong>
              {projectCost.max_iterations != null && ` / ${projectCost.max_iterations}`}
              {projectCost.elapsed_s > 0 && ` · ${Math.round(projectCost.elapsed_s)} s`}
            </Typography>
            {projectCost.stop_reason !== 'unknown' && (
              <Typography variant="caption" color="text.secondary">
                Arrêt :{' '}
                {projectCost.stop_reason === 'approved' && 'Qualité approuvée'}
                {projectCost.stop_reason === 'max_iterations' && 'Plafond itérations atteint'}
                {projectCost.stop_reason === 'cost_cap' && 'Plafond coût atteint'}
              </Typography>
            )}
            {projectCost.by_agent.length > 0 && (
              <Box component="ul" sx={{ m: 0, pl: 2 }}>
                {projectCost.by_agent.slice(0, 8).map((row) => (
                  <Typography component="li" variant="caption" key={row.agent_name}>
                    {row.agent_name} — ${row.usd.toFixed(4)} ({row.input_tokens + row.output_tokens} tokens)
                  </Typography>
                ))}
              </Box>
            )}
          </Stack>
        </PageSection>
        </Box>
      )}

      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}

      {(project.status === 'failed' || project.status === 'stopped') && (
        <Alert severity={project.status === 'stopped' ? 'warning' : 'error'} sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: project.error_message ? 0.5 : 0 }}>
            {project.status === 'stopped' ? 'Pipeline arrêté manuellement' : 'Le pipeline a échoué'}
          </Typography>
          {project.error_message && project.error_message !== 'Arrêté manuellement' && (
            <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {project.error_message}
            </Typography>
          )}
        </Alert>
      )}

      {failedRuns.length > 0 && (
        <Box sx={{ mb: 3 }}>
          {failedRuns.map((run) => (
            <Accordion key={run.id} disableGutters>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="body2" color="error">
                  Agent <strong>{run.agent_name}</strong> — itération {run.iteration} — échoué
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: 12 }}>
                  {run.error}
                </Typography>
              </AccordionDetails>
            </Accordion>
          ))}
        </Box>
      )}

      <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Pipeline" />
        <Tab label="Médias" />
        <Tab label="Aperçu" />
      </Tabs>

      {tab === 0 && (
        <PageSection title="Pipeline agents">
          <PipelineVisualizer
            projectId={id}
            isShort={isShort}
            preparationAgents={pipelinePlan?.preparation}
            iterationFirstAgents={pipelinePlan?.iteration_first}
            iterationRevisionAgents={pipelinePlan?.iteration_revision}
            postProductionAgents={pipelinePlan?.post_production}
            maxIterations={displayMaxIter}
            maxIterationsUnlimited={maxIterationsUnlimited}
            projectStatus={project.status}
            pipelineKickoff={pipelineKickoff}
            agentRuns={agentRuns ?? []}
            criticReports={criticReports ?? []}
            onRunFrom={handleRunFrom}
            onStop={handleStop}
            onRestartFromCritic={handleRestartFromCritic}
            selection={selectedAgent ?? undefined}
            onSelect={handleSelectAgent}
            restartingReportId={restartingReportId}
            actionLoading={actionLoading}
          />
          {selectedAgent ? (
            <>
              <Divider sx={{ my: 3 }} />
              <AgentOutputPanel
                projectId={id}
                selection={selectedAgent}
                agentRuns={agentRuns ?? []}
                criticReports={criticReports ?? []}
                projectStatus={project.status}
                pipelineKickoff={pipelineKickoff}
              />
            </>
          ) : (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 2, fontStyle: 'italic' }}>
              Cliquez sur un agent pour voir son résultat.
            </Typography>
          )}
        </PageSection>
      )}

      {tab === 1 && (
        <MediaValidationPanel projectId={id} projectStatus={project.status} />
      )}

      {tab === 2 && <FinalPreviewSection projectId={id} refreshInterval={isRunning ? 3000 : 0} />}

      {dialog}
    </PageContainer>
  )
}
