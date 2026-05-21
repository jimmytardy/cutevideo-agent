'use client'

import { use } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import AppShell from '@/components/AppShell'
import PipelineVisualizer from '@/components/PipelineVisualizer'
import CriticFeedback from '@/components/CriticFeedback'
import { fetcher, type Project } from '@/lib/api'

interface Props {
  params: Promise<{ id: string }>
}

export default function ProjectDetailPage({ params }: Props) {
  const { id } = use(params)
  const { data: project, isLoading, error } = useSWR<Project>(
    `/api/v1/projects/${id}`,
    fetcher,
    { refreshInterval: 3000 },
  )

  if (isLoading) return <AppShell><CircularProgress sx={{ m: 4 }} /></AppShell>
  if (error || !project) return <AppShell><Alert severity="error">Projet introuvable</Alert></AppShell>

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

        <Divider sx={{ mb: 3 }} />

        <Typography variant="h6" sx={{ mb: 2 }}>Pipeline agents</Typography>
        <PipelineVisualizer projectId={id} />

        <Divider sx={{ my: 3 }} />

        <Typography variant="h6" sx={{ mb: 2 }}>Rapport critique IA</Typography>
        <CriticFeedback projectId={id} />
      </Box>
    </AppShell>
  )
}
