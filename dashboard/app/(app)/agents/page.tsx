'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Typography from '@mui/material/Typography'
import Table from '@mui/material/Table'
import TableHead from '@mui/material/TableHead'
import TableBody from '@mui/material/TableBody'
import TableRow from '@mui/material/TableRow'
import TableCell from '@mui/material/TableCell'
import Tabs from '@mui/material/Tabs'
import Tab from '@mui/material/Tab'
import Box from '@mui/material/Box'
import AgentLlmConfigPanel from '@/components/AgentLlmConfigPanel'
import { PageContainer, PageHeader, EmptyState, LoadingState } from '@/components/layout'
import { fetcher, type AgentRun, type Project } from '@/lib/api'

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  running: 'warning',
  success: 'success',
  failed: 'error',
  pending: 'default',
  skipped: 'default',
}

function AgentsMonitoringTab() {
  const { data: projects, isLoading: loadingProjects } = useSWR<Project[]>('/api/v1/projects', fetcher, {
    refreshInterval: 5000,
  })

  const latestProject = projects?.[0]

  const { data: runs, isLoading: loadingRuns } = useSWR<AgentRun[]>(
    latestProject ? `/api/v1/agents/runs/${latestProject.id}` : null,
    fetcher,
    { refreshInterval: 2000 },
  )

  const isLoading = loadingProjects || loadingRuns

  if (isLoading) return <LoadingState variant="table" count={6} />

  if (!latestProject) {
    return (
      <EmptyState
        title="Aucun projet"
        description="Créez un projet pour monitorer l'exécution des agents."
        actionLabel="Créer une vidéo"
        actionHref="/create"
      />
    )
  }

  return (
    <>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Projet actif : <strong>{latestProject.title || latestProject.theme}</strong>
      </Typography>

      {runs && runs.length > 0 ? (
        <Card>
          <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
            <Table size="small" stickyHeader>
              <TableHead>
                <TableRow>
                  <TableCell>Agent</TableCell>
                  <TableCell>Statut</TableCell>
                  <TableCell>Itération</TableCell>
                  <TableCell>Durée</TableCell>
                  <TableCell>Erreur</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {runs.map((run) => {
                  const duration =
                    run.started_at && run.ended_at
                      ? `${((new Date(run.ended_at).getTime() - new Date(run.started_at).getTime()) / 1000).toFixed(1)}s`
                      : run.started_at
                        ? 'En cours…'
                        : '-'
                  return (
                    <TableRow key={run.id} hover>
                      <TableCell>
                        <Typography variant="body2" fontWeight={600}>
                          {run.agent_name}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <Chip
                          label={run.status ?? 'unknown'}
                          color={STATUS_COLOR[run.status ?? ''] ?? 'default'}
                          size="small"
                        />
                      </TableCell>
                      <TableCell>{run.iteration}</TableCell>
                      <TableCell>{duration}</TableCell>
                      <TableCell>
                        {run.error ? (
                          <Typography variant="caption" color="error" noWrap sx={{ maxWidth: 200, display: 'block' }}>
                            {run.error}
                          </Typography>
                        ) : (
                          '-'
                        )}
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      ) : (
        <EmptyState title="Aucune exécution" description="Les runs d'agents apparaîtront ici une fois le pipeline lancé." />
      )}
    </>
  )
}

export default function AgentsPage() {
  const [tab, setTab] = useState(0)

  return (
    <PageContainer>
      <PageHeader
        title="Agents"
        description="Monitoring du pipeline et configuration des modèles IA par agent."
      />

      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ mb: 3, borderBottom: 1, borderColor: 'divider' }}>
        <Tab label="Monitoring" />
        <Tab label="Modèles IA" />
      </Tabs>

      <Box>{tab === 0 ? <AgentsMonitoringTab /> : <AgentLlmConfigPanel />}</Box>
    </PageContainer>
  )
}
