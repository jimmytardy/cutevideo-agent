'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Grid from '@mui/material/Grid'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import CircularProgress from '@mui/material/CircularProgress'
import LinearProgress from '@mui/material/LinearProgress'
import Tooltip from '@mui/material/Tooltip'
import AppShell from '@/components/AppShell'
import { fetcher, type HealthStatus, type SchedulerJob, type Project, type StorageStats } from '@/lib/api'

const BASE = '/api/v1'

function StatusDot({ ok, label, detail }: { ok: boolean; label: string; detail?: string | null }) {
  const chip = (
    <Chip
      size="small"
      label={label}
      sx={{
        bgcolor: ok ? 'success.main' : 'error.main',
        color: '#fff',
        fontWeight: 600,
        fontSize: '0.75rem',
      }}
    />
  )
  return detail ? <Tooltip title={detail}>{chip}</Tooltip> : chip
}

function BackendStatus() {
  const { data, error, isLoading } = useSWR<HealthStatus>('/health', fetcher, { refreshInterval: 15000 })

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Statut du backend
        </Typography>
        {isLoading && <CircularProgress size={20} />}
        {error && <Alert severity="error" sx={{ mt: 1 }}>Impossible de contacter l'API</Alert>}
        {data && (
          <>
            {(data.s3 === 'error') && (
              <Alert severity="error" sx={{ mb: 2 }}>
                <strong>S3 inaccessible</strong>{data.s3_detail ? ` — ${data.s3_detail}` : ''}
                <br />
                Vérifiez <code>S3_BUCKET</code>, <code>AWS_ACCESS_KEY_ID</code> et <code>S3_REGION</code> dans votre <code>.env</code>.
              </Alert>
            )}
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 1 }}>
              <StatusDot ok={data.database === 'ok'} label="PostgreSQL" />
              <StatusDot ok={data.redis === 'ok'} label="Redis" />
              <StatusDot ok={data.s3 === 'ok'} label="S3" detail={data.s3_detail} />
              <StatusDot ok={data.scheduler === 'running'} label="Scheduler" />
            </Box>
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
              Statut global :{' '}
              <strong style={{ color: data.status === 'ok' ? 'green' : 'red' }}>
                {data.status === 'ok' ? 'Tout est opérationnel' : 'Dégradé'}
              </strong>
            </Typography>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function statusLabel(s: string) {
  const map: Record<string, string> = {
    pending: 'En attente',
    running: 'En cours',
    approved: 'Approuvé',
    rejected: 'Rejeté',
    published: 'Publié',
    failed: 'Échoué',
  }
  return map[s] ?? s
}

function statusColor(s: string): 'default' | 'warning' | 'info' | 'success' | 'error' {
  if (s === 'running') return 'info'
  if (s === 'approved') return 'success'
  if (s === 'published') return 'success'
  if (s === 'failed' || s === 'rejected') return 'error'
  if (s === 'pending') return 'warning'
  return 'default'
}

function RunningProjects() {
  const { data, isLoading } = useSWR<Project[]>(
    `${BASE}/projects?status=running&limit=10`,
    fetcher,
    { refreshInterval: 10000 },
  )

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Vidéos en cours de production
        </Typography>
        {isLoading && <CircularProgress size={20} />}
        {data && data.length === 0 && (
          <Typography variant="body2" color="text.secondary">
            Aucun pipeline actif en ce moment.
          </Typography>
        )}
        {data && data.map((p) => (
          <Box key={p.id} sx={{ mb: 1.5 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Chip size="small" label={statusLabel(p.status)} color={statusColor(p.status)} />
              <Typography variant="body2" fontWeight={600} component="a" href={`/projects/${p.id}`} sx={{ textDecoration: 'none', color: 'text.primary', '&:hover': { textDecoration: 'underline' } }}>
                {p.title ?? p.theme}
              </Typography>
              {p.channel_name && (
                <Typography variant="caption" color="text.secondary">— {p.channel_name}</Typography>
              )}
            </Box>
            <Typography variant="caption" color="text.secondary">
              Démarré le {new Date(p.updated_at).toLocaleString('fr-FR')}
            </Typography>
          </Box>
        ))}
      </CardContent>
    </Card>
  )
}

function formatNextRun(iso: string | null): string {
  if (!iso) return 'Non planifié'
  const d = new Date(iso)
  const diffMs = d.getTime() - Date.now()
  const diffMin = Math.round(diffMs / 60000)
  if (diffMin < 0) return 'Imminent'
  if (diffMin < 60) return `dans ${diffMin} min`
  const diffH = Math.round(diffMin / 60)
  if (diffH < 24) return `dans ${diffH}h`
  return `dans ${Math.round(diffH / 24)}j`
}

function CronSchedule() {
  const { data, isLoading } = useSWR<SchedulerJob[]>(
    `${BASE}/scheduler/jobs`,
    fetcher,
    { refreshInterval: 60000 },
  )

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Prochaines actions des crons
        </Typography>
        {isLoading && <CircularProgress size={20} />}
        {data && data.length === 0 && (
          <Typography variant="body2" color="text.secondary">Scheduler non démarré.</Typography>
        )}
        {data && data.map((job) => (
          <Box key={job.id} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 0.75 }}>
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
              {job.last_run && (
                <Chip
                  size="small"
                  label={job.last_run.status === 'completed' ? '✓' : job.last_run.status === 'failed' ? '✗' : '…'}
                  color={job.last_run.status === 'completed' ? 'success' : job.last_run.status === 'failed' ? 'error' : 'default'}
                  sx={{ minWidth: 28, fontWeight: 700 }}
                />
              )}
              <Typography variant="body2">{job.name ?? job.id}</Typography>
            </Box>
            <Typography variant="caption" color={job.next_run_time ? 'text.secondary' : 'text.disabled'}>
              {formatNextRun(job.next_run_time)}
            </Typography>
          </Box>
        ))}
      </CardContent>
    </Card>
  )
}

function ProjectStats() {
  const statuses = ['running', 'pending', 'approved', 'published', 'failed']
  const { data: all } = useSWR<Project[]>(`${BASE}/projects?limit=200`, fetcher, { refreshInterval: 30000 })

  const counts = statuses.reduce<Record<string, number>>((acc, s) => {
    acc[s] = (all ?? []).filter((p) => p.status === s).length
    return acc
  }, {})

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Résumé des projets
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mt: 1 }}>
          {statuses.map((s) => (
            <Box key={s} sx={{ textAlign: 'center' }}>
              <Typography variant="h5" fontWeight={700}>{counts[s] ?? 0}</Typography>
              <Typography variant="caption" color="text.secondary">{statusLabel(s)}</Typography>
            </Box>
          ))}
          <Box sx={{ textAlign: 'center' }}>
            <Typography variant="h5" fontWeight={700}>{(all ?? []).length}</Typography>
            <Typography variant="caption" color="text.secondary">Total</Typography>
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} Ko`
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} Mo`
  return `${(bytes / 1024 ** 3).toFixed(2)} Go`
}

function S3StorageUsage() {
  const { data, isLoading, error } = useSWR<StorageStats>('/storage/stats', fetcher, { refreshInterval: 60000 })

  const pct = data?.used_pct ?? 0
  const barColor = pct > 90 ? 'error' : pct > 70 ? 'warning' : 'success'

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Espace S3
        </Typography>
        {isLoading && <CircularProgress size={20} />}
        {error && <Typography variant="body2" color="text.secondary">Indisponible</Typography>}
        {data && (
          <>
            {data.bucket && (
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                Bucket : <code>{data.bucket}</code>
              </Typography>
            )}
            <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
              <Typography variant="body2">{formatBytes(data.used_bytes)} utilisés</Typography>
              <Typography variant="body2" color="text.secondary">{formatBytes(data.max_bytes)} quota</Typography>
            </Box>
            <LinearProgress
              variant="determinate"
              value={Math.min(pct, 100)}
              color={barColor}
              sx={{ height: 8, borderRadius: 4 }}
            />
            <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: 'block' }}>
              {pct}% utilisé — {formatBytes(data.max_bytes - data.used_bytes)} disponibles
            </Typography>
          </>
        )}
      </CardContent>
    </Card>
  )
}

function RecentActivity() {
  const { data } = useSWR<Project[]>(`${BASE}/projects?limit=5`, fetcher, { refreshInterval: 30000 })

  return (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          Activité récente
        </Typography>
        {(data ?? []).map((p, i) => (
          <Box key={p.id}>
            {i > 0 && <Divider sx={{ my: 0.75 }} />}
            <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
              <Chip size="small" label={statusLabel(p.status)} color={statusColor(p.status)} />
              <Typography variant="body2" component="a" href={`/projects/${p.id}`} sx={{ textDecoration: 'none', color: 'text.primary', '&:hover': { textDecoration: 'underline' } }}>
                {p.title ?? p.theme}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ ml: 'auto' }}>
                {new Date(p.updated_at).toLocaleString('fr-FR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
              </Typography>
            </Box>
          </Box>
        ))}
      </CardContent>
    </Card>
  )
}

export default function HomePage() {
  return (
    <AppShell>
      <Box sx={{ py: 4, px: 2, maxWidth: 1200, mx: 'auto' }}>
        <Typography variant="h5" fontWeight={700} gutterBottom>
          Vue d'ensemble
        </Typography>

        <Grid container spacing={3}>
          {/* Ligne 1 : statut + crons */}
          <Grid item xs={12} md={6}>
            <BackendStatus />
          </Grid>
          <Grid item xs={12} md={6}>
            <CronSchedule />
          </Grid>

          {/* Ligne 2 : pipeline en cours + stats + S3 */}
          <Grid item xs={12} md={8}>
            <RunningProjects />
          </Grid>
          <Grid item xs={12} md={4} sx={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <ProjectStats />
            <S3StorageUsage />
          </Grid>

          {/* Ligne 3 : activité récente */}
          <Grid item xs={12}>
            <RecentActivity />
          </Grid>
        </Grid>
      </Box>
    </AppShell>
  )
}
