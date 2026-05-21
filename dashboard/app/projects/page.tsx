'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Slider from '@mui/material/Slider'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import AddIcon from '@mui/icons-material/Add'
import AppShell from '@/components/AppShell'
import ProjectCard from '@/components/ProjectCard'
import { createProject, fetchChannels, fetcher, type Channel, type Project } from '@/lib/api'

export default function ProjectsPage() {
  const { data: projects, error, isLoading, mutate } = useSWR<Project[]>(
    '/api/v1/projects',
    fetcher,
    { refreshInterval: 5000 },
  )
  const { data: channels } = useSWR<Channel[]>('/api/v1/channels?active_only=true', () =>
    fetchChannels(true),
  )
  const [filterChannelId, setFilterChannelId] = useState('')
  const [open, setOpen] = useState(false)
  const [channelId, setChannelId] = useState('')
  const [theme, setTheme] = useState('')
  const [duration, setDuration] = useState(1800)
  const [creating, setCreating] = useState(false)

  const filtered =
    filterChannelId && projects
      ? projects.filter((p) => p.channel_id === filterChannelId)
      : projects

  const handleCreate = async () => {
    if (!theme.trim() || !channelId) return
    setCreating(true)
    try {
      await createProject(channelId, theme.trim(), duration)
      await mutate()
      setOpen(false)
      setTheme('')
      setDuration(1800)
    } finally {
      setCreating(false)
    }
  }

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 4 }}>
          <Typography variant="h5">Projets vidéo</Typography>
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
            Nouveau projet
          </Button>
        </Box>

        <TextField
          select
          label="Filtrer par chaîne"
          value={filterChannelId}
          onChange={(e) => setFilterChannelId(e.target.value)}
          sx={{ mb: 3, minWidth: 240 }}
          size="small"
        >
          <MenuItem value="">Toutes les chaînes</MenuItem>
          {channels?.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.name}
            </MenuItem>
          ))}
        </TextField>

        {isLoading && <CircularProgress />}
        {error && <Alert severity="error">Impossible de charger les projets</Alert>}
        {filtered?.length === 0 && (
          <Typography color="text.secondary">Aucun projet — créez-en un !</Typography>
        )}

        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {filtered?.map((p) => (
            <ProjectCard key={p.id} project={p} onRefresh={mutate} />
          ))}
        </Box>
      </Box>

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Nouveau projet vidéo</DialogTitle>
        <DialogContent sx={{ pt: 2 }}>
          <TextField
            select
            label="Chaîne"
            fullWidth
            value={channelId}
            onChange={(e) => setChannelId(e.target.value)}
            sx={{ mb: 2 }}
          >
            {channels?.map((c) => (
              <MenuItem key={c.id} value={c.id}>
                {c.name} ({c.theme_category})
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Sujet de la vidéo"
            placeholder="ex: La bataille de Marignan"
            fullWidth
            value={theme}
            onChange={(e) => setTheme(e.target.value)}
            sx={{ mb: 3 }}
            autoFocus
          />
          <Typography gutterBottom>
            Durée cible : <strong>{Math.round(duration / 60)} min</strong>
          </Typography>
          <Slider
            value={duration}
            onChange={(_, v) => setDuration(v as number)}
            min={600}
            max={3600}
            step={300}
            marks={[
              { value: 600, label: '10min' },
              { value: 1800, label: '30min' },
              { value: 3600, label: '60min' },
            ]}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Annuler</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={!theme.trim() || !channelId || creating}
            startIcon={creating ? <CircularProgress size={16} /> : undefined}
          >
            Créer
          </Button>
        </DialogActions>
      </Dialog>
    </AppShell>
  )
}
