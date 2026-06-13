'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import AppShell from '@/components/AppShell'
import PipelineVisualizer from '@/components/PipelineVisualizer'
import CriticFeedback from '@/components/CriticFeedback'
import { fetcher, type Project, type AgentRun } from '@/lib/api'

interface Props {
  params: { id: string }
}

export default function ProjectDetailPage({ params }: Props) {
  const { id } = params
  const { data: project, isLoading, error } = useSWR<Project>(
    `/api/v1/projects/${id}`,
    fetcher,
    { refreshInterval: 3000 },
  )
  const { data: agentRuns } = useSWR<AgentRun[]>(
    `/api/v1/agents/runs/${id}`,
    fetcher,
    { refreshInterval: project?.status === 'running' ? 3000 : 0 },
  )

  if (isLoading) return <AppShell><CircularProgress sx={{ m: 4 }} /></AppShell>
  if (error || !project) return <AppShell><Alert severity="error">Projet introuvable</Alert></AppShell>

  const failedRuns = agentRuns?.filter((r) => r.status === 'failed' && r.error) ?? []

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Box sx={{ display: 'flex', gap: 2, alignItems: 'center', mb: 3 }}>
          <Typography variant="h5" sx={{ flex: 1 }}>
            {project.title || project.theme}
          </Typography>
          <Chip
            label={project.status}
            color={project.status === 'approved' ? 'success' : project.status === 'failed' ? 'error' : 'default'}
          />
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
          {project.channel_name && <>Chaîne : {project.channel_name} · </>}
          Sujet : {project.theme}
          {project.target_duration_seconds && ` · ${Math.round(project.target_duration_seconds / 60)} min`}
        </Typography>

        {project.status === 'failed' && (
          <Alert severity="error" sx={{ mb: 3 }}>
            <Typography variant="subtitle2" sx={{ mb: project.error_message ? 0.5 : 0 }}>
              Le pipeline a échoué
            </Typography>
            {project.error_message && (
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
          isShort={project.config?.format === 'short_standalone' || project.config?.format === 'short'}
        />

        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" sx={{ mb: 2 }}>Rapport critique IA</Typography>
        <CriticFeedback projectId={id} />
      </Box>
    </AppShell>
  )
}
