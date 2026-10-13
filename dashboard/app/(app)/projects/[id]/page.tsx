'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import Stack from '@mui/material/Stack'
import StopIcon from '@mui/icons-material/Stop'
import ReplayIcon from '@mui/icons-material/Replay'
import DeleteIcon from '@mui/icons-material/Delete'
import { PageContainer, PageHeader, PageSection, LoadingState, useConfirmDialog } from '@/components/layout'
import { projectStatusLabel, projectStatusColor } from '@/lib/status'
import StudioPipeline from '@/components/StudioPipeline'
import FinalPreviewSection from '@/components/FinalPreviewSection'
import {
  fetcher,
  stopPipeline,
  restartPipeline,
  dequeueProject,
  deleteProject,
  projectThumbnailStreamUrl,
  type Project,
  type AgentRun,
  type CriticReport,
  type Scenario,
  type ProjectMetadata,
  type ThumbnailCandidate,
  type StudioBeat,
  type StudioInfo,
} from '@/lib/api'

interface Props {
  params: { id: string }
}

const ACTIVE = ['running', 'queued']

export default function ProjectDetailPage({ params }: Props) {
  const { id } = params
  const router = useRouter()
  const { confirm, dialog } = useConfirmDialog()
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionLoading, setActionLoading] = useState(false)

  const { data: project, isLoading, error, mutate: mutateProject } = useSWR<Project>(
    `/api/v1/projects/${id}`,
    fetcher,
    { refreshInterval: (data) => (ACTIVE.includes(data?.status ?? '') ? 3000 : 0) },
  )
  const active = ACTIVE.includes(project?.status ?? '')
  const refresh = { refreshInterval: active ? 4000 : 0 }
  const { data: agentRuns } = useSWR<AgentRun[]>(`/api/v1/agents/runs/${id}`, fetcher, refresh)
  const { data: criticReports } = useSWR<CriticReport[]>(`/api/v1/projects/${id}/critic-reports`, fetcher, refresh)
  const { data: scenario } = useSWR<Scenario | null>(`/api/v1/projects/${id}/scenario`, fetcher, refresh)
  const { data: metadata } = useSWR<ProjectMetadata | null>(`/api/v1/projects/${id}/metadata`, fetcher, refresh)
  const { data: thumbnails } = useSWR<ThumbnailCandidate[]>(`/api/v1/projects/${id}/thumbnails`, fetcher, refresh)

  if (isLoading) return <LoadingState variant="page" />
  if (error || !project) return <PageContainer><Alert severity="error">Projet introuvable</Alert></PageContainer>

  const isRunning = project.status === 'running'
  const isQueued = project.status === 'queued'
  const canRestart = ['failed', 'stopped', 'approved', 'pending'].includes(project.status)
  const studio = (project.config?.claude_studio ?? null) as StudioInfo | null
  const beats = (scenario?.segments ?? []) as unknown as StudioBeat[]

  const runAction = async (action: () => Promise<unknown>) => {
    setActionError(null)
    setActionLoading(true)
    try {
      await action()
      await mutateProject()
    } catch (e) {
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
    await runAction(async () => {
      await deleteProject(id)
      router.push('/projects')
    })
  }

  const spinner = <CircularProgress size={16} color="inherit" />
  const statusChipColor = projectStatusColor(project.status)

  return (
    <PageContainer>
      <PageHeader
        title={project.title || project.theme}
        description={[
          project.channel_name && `Chaîne : ${project.channel_name}`,
          `Sujet : ${project.theme}`,
          project.target_duration_seconds && `${project.target_duration_seconds} s`,
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
              label={projectStatusLabel(project.status)}
              color={statusChipColor === 'default' ? undefined : statusChipColor}
              size="small"
            />
            {isQueued && (
              <Button variant="outlined" color="warning" size="small" disabled={actionLoading}
                startIcon={actionLoading ? spinner : <StopIcon />} onClick={() => runAction(() => dequeueProject(id))}>
                Retirer de la file
              </Button>
            )}
            {isRunning && (
              <Button variant="contained" color="error" size="small" disabled={actionLoading}
                startIcon={actionLoading ? spinner : <StopIcon />} onClick={() => runAction(() => stopPipeline(id))}>
                Arrêter
              </Button>
            )}
            {canRestart && (
              <Button variant="outlined" size="small" disabled={actionLoading}
                startIcon={actionLoading ? spinner : <ReplayIcon />} onClick={() => runAction(() => restartPipeline(id))}>
                {project.status === 'pending' ? 'Lancer' : 'Relancer'}
              </Button>
            )}
            {!isRunning && !isQueued && (
              <Button variant="outlined" color="error" size="small" disabled={actionLoading}
                startIcon={actionLoading ? spinner : <DeleteIcon />} onClick={handleDelete}>
                Supprimer
              </Button>
            )}
          </Box>
        }
      />

      {isQueued && project.queue_position != null && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Position <strong>#{project.queue_position}</strong>
          {project.queue_length != null && <> sur <strong>{project.queue_length}</strong> projet(s) en file</>}
        </Alert>
      )}
      {actionError && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setActionError(null)}>
          {actionError}
        </Alert>
      )}
      {(project.status === 'failed' || project.status === 'stopped') && (
        <Alert severity={project.status === 'stopped' ? 'warning' : 'error'} sx={{ mb: 3 }}>
          <Typography variant="subtitle2">
            {project.status === 'stopped' ? 'Création arrêtée manuellement' : 'La création a échoué'}
          </Typography>
          {project.error_message && project.error_message !== 'Arrêté manuellement' && (
            <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
              {project.error_message}
            </Typography>
          )}
        </Alert>
      )}

      <Stack spacing={3}>
        <PageSection title="Claude Studio">
          <StudioPipeline agentRuns={agentRuns ?? []} criticReports={criticReports ?? []} />
          {studio && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
              {studio.iterations} itération(s)
              {studio.scores?.length ? ` · scores ${studio.scores.join(' → ')}` : ''}
              {studio.num_turns ? ` · ${studio.num_turns} tours` : ''}
              {typeof studio.cost_usd === 'number' ? ` · ${studio.cost_usd.toFixed(2)} $` : ''}
              {studio.notes ? ` · ${studio.notes}` : ''}
            </Typography>
          )}
        </PageSection>

        <FinalPreviewSection projectId={id} refreshInterval={isRunning ? 5000 : 0} />

        {thumbnails && thumbnails.length > 0 && (
          <PageSection title="Miniatures">
            <Stack direction="row" spacing={2} sx={{ flexWrap: 'wrap', gap: 2 }}>
              {thumbnails.map((thumb, index) => (
                <Box key={index} sx={{ maxWidth: 320 }}>
                  <Box
                    component="img"
                    src={projectThumbnailStreamUrl(id, index)}
                    alt={thumb.prompt ?? `Miniature ${index + 1}`}
                    sx={{ width: '100%', maxHeight: 320, objectFit: 'contain', borderRadius: 1, border: 1, borderColor: 'divider' }}
                  />
                  <Typography variant="caption" color="text.secondary">
                    {thumb.primary ? 'Principale · ' : ''}{thumb.prompt}
                  </Typography>
                </Box>
              ))}
            </Stack>
          </PageSection>
        )}

        {metadata && (metadata.title || metadata.description) && (
          <PageSection title="Publication">
            <Typography variant="subtitle1">{metadata.title}</Typography>
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', mt: 1 }}>
              {metadata.description}
            </Typography>
          </PageSection>
        )}

        {beats.length > 0 && (
          <PageSection title="Script">
            <Stack spacing={1.5}>
              {beats.map((beat, i) => (
                <Box key={i}>
                  <Typography variant="body2">
                    <strong>{i + 1}.</strong> {beat.text}
                    {beat.on_screen_text && (
                      <Chip label={beat.on_screen_text} size="small" sx={{ ml: 1 }} />
                    )}
                  </Typography>
                  {beat.visual_intent && (
                    <Typography variant="caption" color="text.secondary">
                      Visuel : {beat.visual_intent}
                    </Typography>
                  )}
                </Box>
              ))}
            </Stack>
          </PageSection>
        )}

        {studio?.credits && studio.credits.length > 0 && (
          <PageSection title="Crédits médias">
            <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
              {studio.credits.map((credit, i) => (
                <Typography component="li" variant="body2" key={i}>
                  {credit.attribution ?? credit.media} {credit.license ? `(${credit.license})` : ''}
                </Typography>
              ))}
            </Box>
          </PageSection>
        )}
      </Stack>

      {dialog}
    </PageContainer>
  )
}
