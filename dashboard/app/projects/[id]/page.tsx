'use client'

import { useState } from 'react'
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
import AppShell from '@/components/AppShell'
import PipelineVisualizer from '@/components/PipelineVisualizer'
import AgentOutputPanel from '@/components/AgentOutputPanel'
import FinalPreviewSection from '@/components/FinalPreviewSection'
import MediaValidationPanel from '@/components/MediaValidationPanel'
import {
  fetcher,
  stopPipeline,
  restartPipeline,
  runFromStep,
  restartFromCriticIteration,
  updateProjectMaxIterations,
  deleteProject,
  type Project,
  type AgentRun,
  type CriticReport,
  type Scenario,
} from '@/lib/api'
import { selectionKey, getResumeStep, type PipelineSelection } from '@/lib/pipeline'

interface Props {
  params: { id: string }
}

const STATUS_LABEL: Record<string, string> = {
  pending: 'En attente',
  running: 'En cours',
  approved: 'Approuvé',
  failed: 'Échoué',
  stopped: 'Arrêté',
}

export default function ProjectDetailPage({ params }: Props) {
  const { id } = params
  const router = useRouter()
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)
  const [maxIterInput, setMaxIterInput] = useState<string>('')
  const [maxIterSaving, setMaxIterSaving] = useState(false)
  const [selectedAgent, setSelectedAgent] = useState<PipelineSelection | null>(null)
  const [restartingReportId, setRestartingReportId] = useState<string | null>(null)
  const { mutate: swrMutate } = useSWRConfig()

  const { data: project, isLoading, error, mutate: mutateProject } = useSWR<Project>(
    `/api/v1/projects/${id}`,
    fetcher,
    { refreshInterval: 3000 },
  )
  const { data: agentRuns } = useSWR<AgentRun[]>(
    `/api/v1/agents/runs/${id}`,
    fetcher,
    { refreshInterval: ['running', 'stopped', 'pending'].includes(project?.status ?? '') ? 3000 : 0 },
  )
  const { data: criticReports } = useSWR<CriticReport[]>(
    `/api/v1/projects/${id}/critic-reports`,
    fetcher,
    { refreshInterval: project?.status === 'running' ? 5000 : 0 },
  )
  const { data: scenario } = useSWR<Scenario | null>(
    `/api/v1/projects/${id}/scenario`,
    fetcher,
    { refreshInterval: project?.status === 'running' ? 5000 : 0 },
  )

  if (isLoading) return <AppShell><CircularProgress sx={{ m: 4 }} /></AppShell>
  if (error || !project) return <AppShell><Alert severity="error">Projet introuvable</Alert></AppShell>

  const failedRuns = agentRuns?.filter((r) => r.status === 'failed' && r.error) ?? []
  const isRunning = project.status === 'running'
  const canRestart = ['failed', 'stopped', 'approved'].includes(project.status)
  const isShort = project.config?.format === 'short_standalone' || project.config?.format === 'short'
  const resumeTarget = getResumeStep(
    agentRuns ?? [],
    project.status,
    criticReports ?? [],
    isShort,
  )

  const currentMaxIter: number = (project.config?.max_critic_iterations as number | undefined) ?? 5
  const iterCount = criticReports?.length ?? 0

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
    try {
      await restartPipeline(id)
      await mutateProject()
    } catch (e) {
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
      setMaxIterInput('')
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur mise à jour')
    } finally {
      setMaxIterSaving(false)
    }
  }

  const handleRunFrom = async (step: string) => {
    setActionError(null)
    setActionLoading(true)
    try {
      await runFromStep(id, step)
      await mutateProject()
      await Promise.all([
        swrMutate(`/api/v1/projects/${id}/critic-reports`),
        swrMutate(`/api/v1/projects/${id}/scenario`),
        swrMutate(`/api/v1/projects/${id}/media-assets`),
        swrMutate(`/api/v1/projects/${id}/audio`),
        swrMutate(`/api/v1/projects/${id}/videos`),
        swrMutate(`/api/v1/agents/runs/${id}`),
        swrMutate(`/api/v1/agents/status/${id}`),
      ])
    } catch (e) {
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
      await restartFromCriticIteration(id, reportId)
      await mutateProject()
      await Promise.all([
        swrMutate(`/api/v1/projects/${id}/critic-reports`),
        swrMutate(`/api/v1/projects/${id}/scenario`),
        swrMutate(`/api/v1/projects/${id}/media-assets`),
        swrMutate(`/api/v1/projects/${id}/audio`),
        swrMutate(`/api/v1/projects/${id}/videos`),
        swrMutate(`/api/v1/agents/runs/${id}`),
        swrMutate(`/api/v1/agents/status/${id}`),
      ])
    } catch (e) {
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
    try {
      await updateProjectMaxIterations(id, currentMaxIter + 1)
      await mutateProject()
      await restartPipeline(id)
      await mutateProject()
    } catch (e) {
      setActionError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setActionLoading(false)
    }
  }

  const handleDelete = async () => {
    if (!window.confirm(`Supprimer le projet "${project.title || project.theme}" ? Cette action est irréversible.`)) return
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

  const statusColor =
    project.status === 'approved' ? 'success' :
    project.status === 'failed' ? 'error' :
    project.status === 'stopped' ? 'warning' :
    project.status === 'running' ? 'info' : 'default'

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mb: 1 }}>
          <Typography variant="h5" sx={{ flex: 1 }}>
            {project.title || project.theme}
          </Typography>
          <Chip
            label={STATUS_LABEL[project.status] ?? project.status}
            color={statusColor as 'success' | 'error' | 'warning' | 'info' | 'default'}
          />
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          {project.channel_name && <>Chaîne : {project.channel_name} · </>}
          Sujet : {project.theme}
          {project.target_duration_seconds && ` · ${Math.round(project.target_duration_seconds / 60)} min`}
        </Typography>

        <Stack direction="row" spacing={1} sx={{ mb: 3, flexWrap: 'wrap', gap: 1 }}>
          {isRunning && (
            <Button
              variant="contained"
              color="error"
              size="small"
              startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <StopIcon />}
              onClick={handleStop}
              disabled={actionLoading}
            >
              Arrêter le pipeline
            </Button>
          )}
          {resumeTarget && ['stopped', 'failed'].includes(project.status) && (
            <Button
              variant="contained"
              color="primary"
              size="small"
              startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <PlayArrowIcon />}
              onClick={handleResume}
              disabled={actionLoading}
            >
              Reprendre — {resumeTarget.label}
            </Button>
          )}
          {canRestart && (
            <Button
              variant={resumeTarget ? 'outlined' : 'contained'}
              color="primary"
              size="small"
              startIcon={actionLoading ? <CircularProgress size={16} color="inherit" /> : <ReplayIcon />}
              onClick={handleRestart}
              disabled={actionLoading}
            >
              {resumeTarget ? 'Tout recommencer' : 'Relancer le pipeline'}
            </Button>
          )}
          {canRestart && (
            <Tooltip title={`Passe de ${currentMaxIter} à ${currentMaxIter + 1} itérations max et relance`}>
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
          {project.status !== 'running' && (
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

        {/* Max iterations control */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 3, flexWrap: 'wrap' }}>
          <Typography variant="body2" color="text.secondary">
            Itérations : <strong>{iterCount}</strong> réalisées · max actuel : <strong>{currentMaxIter}</strong>
          </Typography>
          <TextField
            size="small"
            type="number"
            placeholder={String(currentMaxIter)}
            value={maxIterInput}
            onChange={(e) => setMaxIterInput(e.target.value)}
            inputProps={{ min: 1, max: 20 }}
            sx={{ width: 90 }}
          />
          <Button
            variant="outlined"
            size="small"
            onClick={handleSaveMaxIter}
            disabled={maxIterSaving || !maxIterInput}
          >
            {maxIterSaving ? <CircularProgress size={14} /> : 'Modifier'}
          </Button>
        </Box>

        {actionError && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
            {actionError}
          </Alert>
        )}

        <Accordion sx={{ mb: 3 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="subtitle1">Validation média (par beat)</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <MediaValidationPanel
              projectId={id}
              projectStatus={project.status}
            />
          </AccordionDetails>
        </Accordion>

        <FinalPreviewSection
          projectId={id}
          refreshInterval={isRunning ? 3000 : 0}
        />

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
                  <Typography
                    variant="body2"
                    sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap', fontSize: 12 }}
                  >
                    {run.error}
                  </Typography>
                </AccordionDetails>
              </Accordion>
            ))}
          </Box>
        )}

        <Divider sx={{ mb: 3 }} />

        <Typography variant="h6" sx={{ mb: 2 }}>Pipeline agents</Typography>
        <PipelineVisualizer
          projectId={id}
          isShort={isShort}
          maxIterations={currentMaxIter}
          projectStatus={project.status}
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
            />
          </>
        ) : (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2, fontStyle: 'italic' }}>
            Cliquez sur un agent pour voir son résultat.
          </Typography>
        )}
      </Box>
    </AppShell>
  )
}
