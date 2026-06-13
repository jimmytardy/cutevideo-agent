'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import Table from '@mui/material/Table'
import TableHead from '@mui/material/TableHead'
import TableBody from '@mui/material/TableBody'
import TableRow from '@mui/material/TableRow'
import TableCell from '@mui/material/TableCell'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import AppShell from '@/components/AppShell'
import { fetcher } from '@/lib/api'

interface JobInfo {
  id: string
  name: string
  schedule: string
  next_run_at: string | null
  last_run: {
    status: string
    started_at: string
    duration_s: number | null
    error: string | null
  } | null
}

interface SchedulerRun {
  id: string
  job_id: string
  status: string
  started_at: string
  ended_at: string | null
  error: string | null
}

const STATUS_COLOR: Record<string, 'default' | 'success' | 'error' | 'warning'> = {
  success: 'success',
  failed: 'error',
  running: 'warning',
}

export default function SchedulerPage() {
  const { data: status, mutate: mutateStatus } = useSWR('/api/v1/scheduler/status', fetcher, {
    refreshInterval: 5000,
  })
  const { data: jobs, mutate: mutateJobs } = useSWR<JobInfo[]>('/api/v1/scheduler/jobs', fetcher, {
    refreshInterval: 5000,
  })
  const { data: runs, mutate: mutateRuns } = useSWR<SchedulerRun[]>(
    '/api/v1/scheduler/runs?limit=20',
    fetcher,
    { refreshInterval: 5000 },
  )

  const triggerJob = async (jobId: string) => {
    await fetch(`/api/v1/scheduler/jobs/${jobId}/run`, { method: 'POST' })
    await Promise.all([mutateJobs(), mutateRuns(), mutateStatus()])
  }

  const toggleScheduler = async (action: 'start' | 'stop') => {
    await fetch(`/api/v1/scheduler/${action}`, { method: 'POST' })
    await mutateStatus()
  }

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 3 }}>Scheduler</Typography>

        {status && (
          <Alert
            severity={status.running ? 'success' : 'warning'}
            sx={{ mb: 3 }}
            action={
              <Button
                size="small"
                onClick={() => toggleScheduler(status.running ? 'stop' : 'start')}
              >
                {status.running ? 'Arrêter' : 'Démarrer'}
              </Button>
            }
          >
            Scheduler {status.running ? 'actif' : 'arrêté'} — {status.jobs_count} jobs configurés
          </Alert>
        )}

        {!jobs && <CircularProgress />}
        {jobs && (
          <Card sx={{ mb: 3 }}>
            <CardContent sx={{ p: 0 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Job</TableCell>
                    <TableCell>Planification</TableCell>
                    <TableCell>Prochain run</TableCell>
                    <TableCell>Dernier statut</TableCell>
                    <TableCell>Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {jobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell>
                        <Typography variant="body2" fontWeight={600}>{job.name}</Typography>
                        <Typography variant="caption" color="text.secondary">{job.id}</Typography>
                      </TableCell>
                      <TableCell>{job.schedule}</TableCell>
                      <TableCell>
                        {job.next_run_at
                          ? new Date(job.next_run_at).toLocaleString('fr-FR')
                          : '—'}
                      </TableCell>
                      <TableCell>
                        {job.last_run ? (
                          <Chip
                            size="small"
                            label={job.last_run.status}
                            color={STATUS_COLOR[job.last_run.status] ?? 'default'}
                          />
                        ) : (
                          '—'
                        )}
                      </TableCell>
                      <TableCell>
                        <Button size="small" variant="outlined" onClick={() => triggerJob(job.id)}>
                          Lancer
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}

        <Typography variant="h6" sx={{ mb: 2 }}>Historique récent</Typography>
        {runs && (
          <Card>
            <CardContent sx={{ p: 0 }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Job</TableCell>
                    <TableCell>Statut</TableCell>
                    <TableCell>Début</TableCell>
                    <TableCell>Erreur</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {runs.map((run) => (
                    <TableRow key={run.id}>
                      <TableCell>{run.job_id}</TableCell>
                      <TableCell>
                        <Chip size="small" label={run.status} color={STATUS_COLOR[run.status] ?? 'default'} />
                      </TableCell>
                      <TableCell>{new Date(run.started_at).toLocaleString('fr-FR')}</TableCell>
                      <TableCell>{run.error ?? '—'}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        )}
      </Box>
    </AppShell>
  )
}
