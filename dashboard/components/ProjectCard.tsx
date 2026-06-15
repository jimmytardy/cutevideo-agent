'use client'

import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardActions from '@mui/material/CardActions'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import Box from '@mui/material/Box'
import Tooltip from '@mui/material/Tooltip'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import VisibilityIcon from '@mui/icons-material/Visibility'
import DeleteIcon from '@mui/icons-material/Delete'
import Link from 'next/link'
import { runPipeline, deleteProject, type Project } from '@/lib/api'

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error' | 'info'> = {
  pending: 'default',
  running: 'warning',
  review: 'info',
  approved: 'success',
  published: 'success',
  failed: 'error',
}

interface ProjectCardProps {
  project: Project
  onRefresh: () => void
}

export default function ProjectCard({ project, onRefresh }: ProjectCardProps) {
  const durationMin = project.target_duration_seconds
    ? Math.round(project.target_duration_seconds / 60)
    : null

  const handleRun = async () => {
    await runPipeline(project.id)
    onRefresh()
  }

  const handleDelete = async () => {
    if (!window.confirm(`Supprimer "${project.title || project.theme}" ? Cette action est irréversible.`)) return
    try {
      await deleteProject(project.id)
      onRefresh()
    } catch (e) {
      window.alert(e instanceof Error ? e.message : 'Erreur suppression')
    }
  }

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
          <Typography variant="h6" sx={{ flex: 1, mr: 1 }}>
            {project.title || project.theme}
          </Typography>
          <Chip
            label={project.status}
            color={STATUS_COLOR[project.status] ?? 'default'}
            size="small"
          />
        </Box>
        {project.channel_name && (
          <Chip label={project.channel_name} size="small" sx={{ mb: 1 }} variant="outlined" />
        )}
        <Typography variant="body2" color="text.secondary" noWrap>
          {project.theme}
        </Typography>
        {project.status === 'failed' && project.error_message && (
          <Tooltip title={project.error_message} placement="bottom-start">
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mt: 1 }}>
              <ErrorOutlineIcon color="error" fontSize="small" />
              <Typography variant="caption" color="error" noWrap sx={{ maxWidth: 220 }}>
                {project.error_message}
              </Typography>
            </Box>
          </Tooltip>
        )}
        {durationMin && (
          <Typography variant="caption" color="text.secondary">
            Durée cible : {durationMin} min
          </Typography>
        )}
        <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 0.5 }}>
          Créé le {new Date(project.created_at).toLocaleDateString('fr-FR')}
        </Typography>
      </CardContent>
      <CardActions>
        <Button
          size="small"
          startIcon={<PlayArrowIcon />}
          onClick={handleRun}
          disabled={project.status === 'running'}
          variant="contained"
        >
          Lancer
        </Button>
        <Button
          size="small"
          component={Link}
          href={`/projects/${project.id}`}
          startIcon={<VisibilityIcon />}
        >
          Détails
        </Button>
        {project.status !== 'running' && (
          <Button
            size="small"
            color="error"
            startIcon={<DeleteIcon />}
            onClick={handleDelete}
          >
            Supprimer
          </Button>
        )}
      </CardActions>
    </Card>
  )
}
