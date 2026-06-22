'use client'

import { useState } from 'react'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardActions from '@mui/material/CardActions'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import IconButton from '@mui/material/IconButton'
import Box from '@mui/material/Box'
import Tooltip from '@mui/material/Tooltip'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import VisibilityIcon from '@mui/icons-material/Visibility'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import Link from 'next/link'
import { useConfirmDialog } from '@/components/layout'
import { projectStatusColor, projectStatusLabel } from '@/lib/status'
import { runPipeline, deleteProject, type Project } from '@/lib/api'

interface ProjectCardProps {
  project: Project
  onRefresh: () => void
}

export default function ProjectCard({ project, onRefresh }: ProjectCardProps) {
  const { confirm, dialog } = useConfirmDialog()
  const [deleting, setDeleting] = useState(false)

  const durationMin = project.target_duration_seconds
    ? Math.round(project.target_duration_seconds / 60)
    : null

  const handleRun = async () => {
    await runPipeline(project.id)
    onRefresh()
  }

  const handleDelete = async () => {
    const ok = await confirm({
      title: 'Supprimer le projet',
      message: `Supprimer « ${project.title || project.theme} » ? Cette action est irréversible.`,
      confirmLabel: 'Supprimer',
      confirmColor: 'error',
    })
    if (!ok) return
    setDeleting(true)
    try {
      await deleteProject(project.id)
      onRefresh()
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Card
        sx={{
          height: '100%',
          display: 'flex',
          flexDirection: 'column',
          transition: 'box-shadow 0.2s, transform 0.2s',
          '&:hover': {
            boxShadow: (t) => (t.palette.mode === 'light' ? 4 : 2),
            transform: 'translateY(-2px)',
          },
        }}
      >
        <CardContent sx={{ flex: 1 }}>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
            <Typography variant="h6" sx={{ flex: 1, mr: 1, fontSize: '1rem' }}>
              {project.title || project.theme}
            </Typography>
            <Chip
              label={projectStatusLabel(project.status)}
              color={projectStatusColor(project.status)}
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
        <CardActions sx={{ px: 2, pb: 2, pt: 0 }}>
          <Button
            size="small"
            startIcon={<PlayArrowIcon />}
            onClick={handleRun}
            disabled={project.status === 'running'}
            variant="contained"
          >
            Lancer
          </Button>
          <Button size="small" component={Link} href={`/projects/${project.id}`} startIcon={<VisibilityIcon />}>
            Détails
          </Button>
          {project.status !== 'running' && (
            <Tooltip title="Supprimer">
              <IconButton size="small" color="error" onClick={handleDelete} disabled={deleting} aria-label="Supprimer">
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Tooltip>
          )}
        </CardActions>
      </Card>
      {dialog}
    </>
  )
}
