'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Snackbar from '@mui/material/Snackbar'
import Table from '@mui/material/Table'
import TableHead from '@mui/material/TableHead'
import TableBody from '@mui/material/TableBody'
import TableRow from '@mui/material/TableRow'
import TableCell from '@mui/material/TableCell'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import AdminGuard from '@/components/AdminGuard'
import { PageContainer, PageHeader, PageSection, LoadingState } from '@/components/layout'
import { fetcher, setSchedulerRunning, triggerSchedulerJob } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { runStatusColor } from '@/lib/status'

interface JobInfo {
  id: string
  name: string
  schedule: string
  description?: string
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


interface SchedulerStatus {
  running: boolean
  jobs_count: number
}

export default function SchedulerPage() {
  const { data: status, mutate: mutateStatus } = useSWR<SchedulerStatus>('/api/v1/scheduler/status', fetcher, {
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

  const [launching, setLaunching] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  const jobName = (jobId: string) => jobs?.find((j) => j.id === jobId)?.name ?? jobId

  const triggerJob = async (job: JobInfo) => {
    setLaunching(job.id)
    try {
      try {
        await triggerSchedulerJob(job.id)
      } catch (e) {
        setToast(`Échec du lancement de « ${job.name} » : ${e instanceof Error ? e.message : String(e)}`)
        return
      }
      setToast(`« ${job.name} » lancé — suivez sa progression dans l'historique ci-dessous.`)
      await Promise.all([mutateJobs(), mutateRuns(), mutateStatus()])
    } finally {
      setLaunching(null)
    }
  }

  const toggleScheduler = async (action: 'start' | 'stop') => {
    try {
      await setSchedulerRunning(action)
    } catch (e) {
      setToast(`Échec : ${e instanceof Error ? e.message : String(e)}`)
    }
    await mutateStatus()
  }

  return (
    <AdminGuard>
      <PageContainer>
        <PageHeader
          title="Scheduler"
          description="Comprenez le rôle de chaque agent planifié, lancez-le à la volée sans attendre son créneau, et consultez l'historique d'exécution."
        />

        {status && (
          <Alert
            severity={status.running ? 'success' : 'warning'}
            sx={{ mb: 3 }}
            action={
              <Button size="small" onClick={() => toggleScheduler(status.running ? 'stop' : 'start')}>
                {status.running ? 'Arrêter' : 'Démarrer'}
              </Button>
            }
          >
            Scheduler {status.running ? 'actif' : 'arrêté'} — {status.jobs_count} jobs configurés
          </Alert>
        )}

        <PageSection title="Jobs planifiés">
          {!jobs && <LoadingState variant="table" count={4} />}
          {jobs && (
            <Card>
              <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
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
                      <TableRow key={job.id} hover>
                        <TableCell sx={{ maxWidth: 360 }}>
                          <Typography variant="body2" fontWeight={600}>
                            {job.name}
                          </Typography>
                          {job.description && (
                            <Typography variant="caption" color="text.secondary">
                              {job.description}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>{job.schedule}</TableCell>
                        <TableCell>
                          {formatDateTime(job.next_run_at)}
                        </TableCell>
                        <TableCell>
                          {job.last_run ? (
                            <Chip
                              size="small"
                              label={job.last_run.status}
                              color={runStatusColor(job.last_run.status)}
                            />
                          ) : (
                            '—'
                          )}
                        </TableCell>
                        <TableCell>
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={launching === job.id}
                            startIcon={
                              launching === job.id ? <CircularProgress size={14} color="inherit" /> : undefined
                            }
                            onClick={() => triggerJob(job)}
                          >
                            {launching === job.id ? 'Lancement…' : 'Lancer maintenant'}
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </PageSection>

        <PageSection title="Historique récent">
          {runs && (
            <Card>
              <CardContent sx={{ p: 0, '&:last-child': { pb: 0 } }}>
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
                      <TableRow key={run.id} hover>
                        <TableCell>{jobName(run.job_id)}</TableCell>
                        <TableCell>
                          <Chip size="small" label={run.status} color={runStatusColor(run.status)} />
                        </TableCell>
                        <TableCell>{formatDateTime(run.started_at)}</TableCell>
                        <TableCell>{run.error ?? '—'}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}
        </PageSection>

        <Snackbar
          open={Boolean(toast)}
          autoHideDuration={5000}
          onClose={() => setToast(null)}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
        >
          <Alert severity="info" onClose={() => setToast(null)} sx={{ width: '100%' }}>
            {toast}
          </Alert>
        </Snackbar>
      </PageContainer>
    </AdminGuard>
  )
}
