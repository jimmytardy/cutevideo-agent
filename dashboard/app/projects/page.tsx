'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Link from 'next/link'
import AppShell from '@/components/AppShell'
import ProjectCard from '@/components/ProjectCard'
import { fetchChannels, fetcher, type Channel, type Project } from '@/lib/api'

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

  const filtered =
    filterChannelId && projects
      ? projects.filter((p) => p.channel_id === filterChannelId)
      : projects

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 4 }}>
          Projets vidéo
        </Typography>

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
          <Typography color="text.secondary">
            Aucun projet —{' '}
            <Link href="/create" style={{ color: 'inherit' }}>
              créez une vidéo
            </Link>{' '}
            pour en ajouter un.
          </Typography>
        )}

        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {filtered?.map((p) => (
            <ProjectCard key={p.id} project={p} onRefresh={mutate} />
          ))}
        </Box>
      </Box>
    </AppShell>
  )
}
