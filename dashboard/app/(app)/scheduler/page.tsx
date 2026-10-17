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
import Switch from '@mui/material/Switch'
import Stack from '@mui/material/Stack'
import TextField from '@mui/material/TextField'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import FormControlLabel from '@mui/material/FormControlLabel'
import AdminGuard from '@/components/AdminGuard'
import { PageContainer, PageHeader, PageSection, LoadingState } from '@/components/layout'
import { fetcher, setSchedulerRunning, triggerSchedulerJob, updateSchedulerJob } from '@/lib/api'
import { formatDateTime } from '@/lib/format'
import { runStatusColor } from '@/lib/status'

interface JobInfo {
  id: string
  name: string
  description?: string
  enabled: boolean
  cron: string
  timezone: string
  params: Record<string, number>
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
  enabled: boolean
  process_allowed: boolean
  jobs_count: number
}

const PARAM_LABELS: Record<string, string> = {
  work_files_days: 'Fichiers de travail et vidéos non publiées (jours)',
  media_days: 'Toutes les vidéos, publiées comprises (jours)',
}

interface JobDraft {
  job: JobInfo
  enabled: boolean
  cron: string
  timezone: string
  params: Record<string, string>
}

function JobConfigDialog({
  draft,
  onChange,
  onClose,
  onSave,
  saving,
  error,
}: {
  draft: JobDraft
  onChange: (draft: JobDraft) => void
  onClose: () => void
  onSave: () => void
  saving: boolean
  error: string | null
}) {
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Planification — {draft.job.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 1 }}>
          <FormControlLabel
            control={
              <Switch checked={draft.enabled} onChange={(e) => onChange({ ...draft, enabled: e.target.checked })} />
            }
            label={draft.enabled ? 'Job activé' : 'Job désactivé'}
          />
          <TextField
            label="Cron"
            value={draft.cron}
            onChange={(e) => onChange({ ...draft, cron: e.target.value })}
            helperText="5 champs : minute heure jour mois jour_semaine (ex. 0 6 * * *, */15 * * * *, 0 7-23 * * *)"
            size="small"
          />
          <TextField
            label="Fuseau horaire"
            value={draft.timezone}
            onChange={(e) => onChange({ ...draft, timezone: e.target.value })}
            helperText="Ex. Europe/Paris, UTC"
            size="small"
          />
          {Object.keys(draft.params).map((key) => (
            <TextField
              key={key}
              label={PARAM_LABELS[key] ?? key}
              type="number"
              value={draft.params[key]}
              onChange={(e) =>
                onChange({
                  ...draft,
                  params: { ...draft.params, [key]: e.target.value },
                })
              }
              inputProps={{ min: 0 }}
              size="small"
            />
          ))}
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Annuler</Button>
        <Button variant="contained" onClick={onSave} disabled={saving}>
          {saving ? 'Enregistrement…' : 'Enregistrer'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default function SchedulerPage() {
  const { data: status, mutate: mutateStatus } = useSWR<SchedulerStatus>('/api/v1/scheduler/status', fetcher, {
    refreshInterval: 5000,
  })
  const { data: jobs, mutate: mutateJobs } = useSWR<JobInfo[]>('/api/v1/scheduler/jobs', fetcher, {
    refreshInterval: 5000,
  })
  const { data: runs, mutate: mutateRuns } = useSWR<SchedulerRun[]>('/api/v1/scheduler/runs?limit=20', fetcher, {
    refreshInterval: 5000,
  })

  const [launching, setLaunching] = useState<string | null>(null)
  const [toast, setToast] = useState<string | null>(null)
  const [draft, setDraft] = useState<JobDraft | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const openConfig = (job: JobInfo) => {
    setSaveError(null)
    setDraft({
      job,
      enabled: job.enabled,
      cron: job.cron,
      timezone: job.timezone,
      params: Object.fromEntries(Object.entries(job.params ?? {}).map(([k, v]) => [k, String(v)])),
    })
  }

  const saveConfig = async () => {
    if (!draft) return
    const params = Object.fromEntries(Object.entries(draft.params).map(([k, v]) => [k, Number(v)]))
    setSaving(true)
    setSaveError(null)
    try {
      await updateSchedulerJob(draft.job.id, {
        enabled: draft.enabled,
        cron: draft.cron,
        timezone: draft.timezone,
        ...(Object.keys(params).length ? { params } : {}),
      })
      setDraft(null)
      setToast(`Planification de « ${draft.job.name} » enregistrée.`)
      await mutateJobs()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e))
    } finally {
      setSaving(false)
    }
  }

  const toggleJob = async (job: JobInfo, enabled: boolean) => {
    try {
      await updateSchedulerJob(job.id, { enabled })
    } catch (e) {
      setToast(`Échec : ${e instanceof Error ? e.message : String(e)}`)
    }
    await mutateJobs()
  }

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
    await Promise.all([mutateStatus(), mutateJobs()])
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
              <Button size="small" onClick={() => toggleScheduler(status.enabled ? 'stop' : 'start')}>
                {status.enabled ? 'Désactiver' : 'Activer'}
              </Button>
            }
          >
            Scheduler {status.running ? 'actif' : 'arrêté'} — {status.jobs_count} jobs configurés
            {!status.process_allowed &&
              " · bloqué sur ce serveur par SCHEDULER_ENABLED=false (le réglage est enregistré mais ne s'applique pas ici)"}
            {status.process_allowed && !status.enabled && ' · désactivé (réglage enregistré en base)'}
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
                      <TableCell>Actif</TableCell>
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
                        <TableCell>
                          <Switch
                            size="small"
                            checked={job.enabled}
                            onChange={(e) => toggleJob(job, e.target.checked)}
                            inputProps={{ 'aria-label': `Activer ${job.name}` }}
                          />
                        </TableCell>
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
                        <TableCell>
                          <Typography variant="body2" sx={{ fontFamily: 'monospace' }}>
                            {job.cron}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {job.timezone}
                            {Object.entries(job.params ?? {}).map(([k, v]) => ` · ${k} = ${v}`)}
                          </Typography>
                        </TableCell>
                        <TableCell>{formatDateTime(job.next_run_at)}</TableCell>
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
                          <Stack direction="row" spacing={1}>
                            <Button size="small" onClick={() => openConfig(job)}>
                              Configurer
                            </Button>
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
                          </Stack>
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

        {draft && (
          <JobConfigDialog
            draft={draft}
            onChange={setDraft}
            onClose={() => setDraft(null)}
            onSave={saveConfig}
            saving={saving}
            error={saveError}
          />
        )}

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
