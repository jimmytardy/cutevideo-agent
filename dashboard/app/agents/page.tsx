'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Table from '@mui/material/Table'
import TableHead from '@mui/material/TableHead'
import TableBody from '@mui/material/TableBody'
import TableRow from '@mui/material/TableRow'
import TableCell from '@mui/material/TableCell'
import AppShell from '@/components/AppShell'
import { fetcher, type AgentRun } from '@/lib/api'

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  running: 'warning',
  success: 'success',
  failed: 'error',
  pending: 'default',
  skipped: 'default',
}

export default function AgentsPage() {
  const { data: projects, isLoading: loadingProjects } = useSWR('/api/v1/projects', fetcher, {
    refreshInterval: 5000,
  })

  const latestProject = projects?.[0]

  const { data: runs, isLoading: loadingRuns } = useSWR<AgentRun[]>(
    latestProject ? `/api/v1/agents/runs/${latestProject.id}` : null,
    fetcher,
    { refreshInterval: 2000 },
  )

  const isLoading = loadingProjects || loadingRuns

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 1 }}>Monitoring agents</Typography>
        {latestProject && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
            Projet actif : {latestProject.title || latestProject.theme}
          </Typography>
        )}

        {isLoading && <CircularProgress />}
        {!isLoading && !latestProject && (
          <Alert severity="info">Aucun projet trouvé — créez-en un d&apos;abord.</Alert>
        )}

        {runs && runs.length > 0 && (
          <Card>
            <CardContent sx={{ p: 0 }}>
              <Table size="small">
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
                      <TableRow key={run.id}>
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
                          ) : '-'}
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </Box>
    </AppShell>
  )
}
