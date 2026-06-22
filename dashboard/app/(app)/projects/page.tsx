'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Button from '@mui/material/Button'
import AddIcon from '@mui/icons-material/Add'
import Link from 'next/link'
import ProjectCard from '@/components/ProjectCard'
import {
  PageContainer,
  PageHeader,
  FilterBar,
  EmptyState,
  LoadingState,
  ErrorState,
} from '@/components/layout'
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
    filterChannelId && projects ? projects.filter((p) => p.channel_id === filterChannelId) : projects

  return (
    <PageContainer>
      <PageHeader
        title="Projets vidéo"
        description="Gérez vos productions en cours, relancez un pipeline ou consultez les détails."
        actions={
          <Button component={Link} href="/create" variant="contained" startIcon={<AddIcon />}>
            Créer une vidéo
          </Button>
        }
      />

      <FilterBar>
        <TextField
          select
          label="Filtrer par chaîne"
          value={filterChannelId}
          onChange={(e) => setFilterChannelId(e.target.value)}
          sx={{ minWidth: 240 }}
        >
          <MenuItem value="">Toutes les chaînes</MenuItem>
          {channels?.map((c) => (
            <MenuItem key={c.id} value={c.id}>
              {c.name}
            </MenuItem>
          ))}
        </TextField>
      </FilterBar>

      {isLoading && <LoadingState count={6} />}
      {error && <ErrorState message="Impossible de charger les projets" onRetry={() => mutate()} />}
      {!isLoading && !error && filtered?.length === 0 && (
        <EmptyState
          title="Aucun projet"
          description="Lancez votre première production vidéo pour voir apparaître vos projets ici."
          actionLabel="Créer une vidéo"
          actionHref="/create"
        />
      )}

      {!isLoading && filtered && filtered.length > 0 && (
        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {filtered.map((p) => (
            <ProjectCard key={p.id} project={p} onRefresh={mutate} />
          ))}
        </Box>
      )}
    </PageContainer>
  )
}
