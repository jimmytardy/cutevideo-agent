'use client'

import { useEffect, useRef, useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Slider from '@mui/material/Slider'
import ToggleButton from '@mui/material/ToggleButton'
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup'
import Stepper from '@mui/material/Stepper'
import Step from '@mui/material/Step'
import StepLabel from '@mui/material/StepLabel'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import AccessTimeIcon from '@mui/icons-material/AccessTime'
import MovieIcon from '@mui/icons-material/Movie'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import DeleteIcon from '@mui/icons-material/Delete'
import PublishIcon from '@mui/icons-material/Publish'
import YouTubeIcon from '@mui/icons-material/YouTube'
import AppShell from '@/components/AppShell'
import PipelineVisualizer from '@/components/PipelineVisualizer'
import {
  createProject,
  deleteProject,
  fetchChannels,
  fetchProjectVideos,
  publishProject,
  runPipeline,
  fetcher,
  type Channel,
  type Project,
  type Video,
} from '@/lib/api'

type VideoType = 'short' | 'long'

const STEPS = ['Configurer', 'Estimation', 'Génération', 'Résultat']

const PLATFORMS = [
  { id: 'youtube', label: 'YouTube', icon: <YouTubeIcon sx={{ color: '#FF0000' }} /> },
  { id: 'tiktok', label: 'TikTok', icon: <MovieIcon sx={{ color: '#010101' }} /> },
  { id: 'instagram', label: 'Instagram', icon: <MovieIcon sx={{ color: '#E1306C' }} /> },
]

function estimateMinutes(type: VideoType, durationSeconds: number): number {
  if (type === 'short') return 8
  const targetMin = durationSeconds / 60
  return Math.round(targetMin * 1.3 + 10)
}

export default function CreatePage() {
  const { data: channels } = useSWR<Channel[]>('/api/v1/channels?active_only=true', () =>
    fetchChannels(true),
  )

  // Step 0 — form
  const [step, setStep] = useState(0)
  const [channelId, setChannelId] = useState('')
  const [prompt, setPrompt] = useState('')
  const [videoType, setVideoType] = useState<VideoType>('long')
  const [durationSeconds, setDurationSeconds] = useState(1200) // 20 min default

  // Step 2 — pipeline
  const [projectId, setProjectId] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  // Step 3 — result
  const [videos, setVideos] = useState<Video[]>([])
  const [publishingPlatform, setPublishingPlatform] = useState<string | null>(null)
  const [publishSuccess, setPublishSuccess] = useState<string | null>(null)
  const [publishError, setPublishError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState(false)

  const { data: project } = useSWR<Project>(
    projectId ? `/api/v1/projects/${projectId}` : null,
    fetcher,
    { refreshInterval: step === 2 ? 3000 : 0 },
  )

  // Advance to result step when pipeline finishes
  const advancedRef = useRef(false)
  useEffect(() => {
    if (step !== 2 || !project || advancedRef.current) return
    if (project.status === 'approved' || project.status === 'failed') {
      advancedRef.current = true
      if (project.status === 'approved' && projectId) {
        fetchProjectVideos(projectId).then(setVideos)
      }
      setStep(3)
    }
  }, [project, step, projectId])

  const selectedChannel = channels?.find((c) => c.id === channelId)
  const estimatedMin = estimateMinutes(videoType, durationSeconds)
  const durationLabel =
    videoType === 'short' ? '60 sec (Short)' : `${Math.round(durationSeconds / 60)} min`

  const targetSeconds = videoType === 'short' ? 60 : durationSeconds

  const handleLaunch = async () => {
    if (!channelId || !prompt.trim()) return
    setLaunching(true)
    setCreateError(null)
    try {
      const created = await createProject(channelId, prompt.trim(), targetSeconds)
      setProjectId(created.id)
      await runPipeline(created.id)
      advancedRef.current = false
      setStep(2)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setLaunching(false)
    }
  }

  const handlePublish = async (platform: string) => {
    if (!projectId) return
    setPublishingPlatform(platform)
    setPublishError(null)
    try {
      await publishProject(projectId, platform)
      setPublishSuccess(platform)
    } catch (e) {
      setPublishError(e instanceof Error ? e.message : 'Erreur publication')
    } finally {
      setPublishingPlatform(null)
    }
  }

  const handleDelete = async () => {
    if (!projectId) return
    setDeleting(true)
    try {
      await deleteProject(projectId)
      // Reset to start
      setStep(0)
      setProjectId(null)
      setVideos([])
      setPrompt('')
      setPublishSuccess(null)
      advancedRef.current = false
    } finally {
      setDeleting(false)
    }
  }

  const approvedVideo = videos.find((v) => v.status === 'approved') ?? videos[0] ?? null

  return (
    <AppShell>
      <Box sx={{ maxWidth: 760, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 4 }}>
          Créer une vidéo
        </Typography>

        <Stepper activeStep={step} sx={{ mb: 5 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {/* ── Step 0 : Formulaire ── */}
        {step === 0 && (
          <Stack spacing={3}>
            <TextField
              select
              label="Chaîne"
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              fullWidth
            >
              {channels?.map((c) => (
                <MenuItem key={c.id} value={c.id}>
                  {c.name} — {c.theme_category}
                </MenuItem>
              ))}
            </TextField>

            <TextField
              label="Sujet / prompt"
              placeholder="ex: La chute de l'Empire romain d'Occident"
              multiline
              minRows={3}
              fullWidth
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
            />

            <Box>
              <Typography variant="body2" sx={{ mb: 1.5 }}>
                Type de vidéo
              </Typography>
              <ToggleButtonGroup
                value={videoType}
                exclusive
                onChange={(_, v) => v && setVideoType(v)}
                size="small"
              >
                <ToggleButton value="short">Short (≤ 60s)</ToggleButton>
                <ToggleButton value="long">Vidéo longue</ToggleButton>
              </ToggleButtonGroup>
            </Box>

            {videoType === 'long' && (
              <Box>
                <Typography variant="body2" gutterBottom>
                  Durée cible :{' '}
                  <strong>{Math.round(durationSeconds / 60)} min</strong>
                </Typography>
                <Slider
                  value={durationSeconds}
                  onChange={(_, v) => setDurationSeconds(v as number)}
                  min={300}
                  max={3600}
                  step={300}
                  marks={[
                    { value: 300, label: '5 min' },
                    { value: 900, label: '15 min' },
                    { value: 1800, label: '30 min' },
                    { value: 3600, label: '60 min' },
                  ]}
                />
              </Box>
            )}

            <Box sx={{ display: 'flex', justifyContent: 'flex-end' }}>
              <Button
                variant="contained"
                size="large"
                disabled={!channelId || !prompt.trim()}
                onClick={() => setStep(1)}
              >
                Suivant
              </Button>
            </Box>
          </Stack>
        )}

        {/* ── Step 1 : Estimation ── */}
        {step === 1 && (
          <Stack spacing={3}>
            <Paper variant="outlined" sx={{ p: 3, borderRadius: 2 }}>
              <Typography variant="h6" sx={{ mb: 2 }}>
                Récapitulatif
              </Typography>
              <Stack spacing={1.5}>
                <Row label="Chaîne" value={selectedChannel?.name ?? channelId} />
                <Row label="Sujet" value={prompt} />
                <Row label="Type" value={videoType === 'short' ? 'Short' : 'Vidéo longue'} />
                <Row label="Durée cible" value={durationLabel} />
              </Stack>
            </Paper>

            <Paper
              variant="outlined"
              sx={{ p: 3, borderRadius: 2, borderColor: 'primary.main', bgcolor: 'primary.dark' }}
            >
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                <AccessTimeIcon color="primary" />
                <Typography variant="h6">
                  Temps de réalisation estimé
                </Typography>
              </Box>
              <Typography variant="h3" sx={{ mt: 1, fontWeight: 700 }}>
                ~{estimatedMin} min
              </Typography>
              <Typography variant="caption" color="text.secondary">
                Estimation indicative — dépend de la charge serveur et de la complexité du sujet
              </Typography>
            </Paper>

            {createError && <Alert severity="error">{createError}</Alert>}

            <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
              <Button onClick={() => setStep(0)}>Retour</Button>
              <Button
                variant="contained"
                size="large"
                onClick={handleLaunch}
                disabled={launching}
                startIcon={launching ? <CircularProgress size={18} /> : <MovieIcon />}
              >
                {launching ? 'Lancement…' : 'Lancer la génération'}
              </Button>
            </Box>
          </Stack>
        )}

        {/* ── Step 2 : Génération en cours ── */}
        {step === 2 && projectId && (
          <Stack spacing={3} alignItems="center">
            <Box sx={{ textAlign: 'center' }}>
              <CircularProgress size={56} sx={{ mb: 2 }} />
              <Typography variant="h6">Génération en cours…</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Temps estimé : ~{estimatedMin} min · Pipeline en cours d&apos;exécution
              </Typography>
            </Box>

            {project && (
              <Chip
                label={project.status}
                color={
                  project.status === 'running'
                    ? 'warning'
                    : project.status === 'approved'
                    ? 'success'
                    : project.status === 'failed'
                    ? 'error'
                    : 'default'
                }
              />
            )}

            <Box sx={{ width: '100%' }}>
              <Typography variant="subtitle2" sx={{ mb: 1 }}>
                Progression des agents
              </Typography>
              <PipelineVisualizer projectId={projectId} />
            </Box>
          </Stack>
        )}

        {/* ── Step 3 : Résultat ── */}
        {step === 3 && projectId && (
          <Stack spacing={3}>
            {project?.status === 'failed' ? (
              <Alert severity="error">
                La génération a échoué. Consultez les détails dans{' '}
                <a href={`/projects/${projectId}`}>la page projet</a>.
              </Alert>
            ) : (
              <Alert severity="success" icon={<CheckCircleIcon />}>
                Vidéo générée avec succès !
              </Alert>
            )}

            {/* Video preview */}
            {approvedVideo?.local_path && (
              <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
                <Typography variant="subtitle2" sx={{ mb: 1.5 }}>
                  Prévisualisation
                </Typography>
                <Box
                  component="video"
                  controls
                  sx={{ width: '100%', borderRadius: 1, maxHeight: 420 }}
                  src={`/api/v1/media/temp/${projectId}?path=${encodeURIComponent(approvedVideo.local_path)}`}
                />
                <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
                  {approvedVideo.video_type && (
                    <Chip label={approvedVideo.video_type} size="small" />
                  )}
                  {approvedVideo.duration_s && (
                    <Chip
                      label={`${Math.round(approvedVideo.duration_s)}s`}
                      size="small"
                      variant="outlined"
                    />
                  )}
                </Stack>
              </Paper>
            )}

            {!approvedVideo?.local_path && project?.status === 'approved' && (
              <Alert severity="info">
                Vidéo approuvée — fichier non disponible localement (stockage S3 ou chemin inaccessible).
              </Alert>
            )}

            <Divider />

            {/* Publish */}
            {project?.status === 'approved' && (
              <Box>
                <Typography variant="subtitle1" fontWeight={600} sx={{ mb: 2 }}>
                  Publier sur
                </Typography>

                {publishSuccess && (
                  <Alert severity="success" sx={{ mb: 2 }}>
                    Publication {publishSuccess} créée — sera envoyée lors du prochain passage du scheduler.
                  </Alert>
                )}
                {publishError && (
                  <Alert severity="error" sx={{ mb: 2 }}>
                    {publishError}
                  </Alert>
                )}

                <Stack direction="row" spacing={2} flexWrap="wrap">
                  {PLATFORMS.map((p) => {
                    const channelSupports =
                      p.id === 'youtube'
                        ? !!selectedChannel?.youtube_channel_id
                        : p.id === 'tiktok'
                        ? !!selectedChannel?.tiktok_enabled
                        : p.id === 'instagram'
                        ? !!selectedChannel?.instagram_page_id
                        : false

                    return (
                      <Button
                        key={p.id}
                        variant={publishSuccess === p.id ? 'contained' : 'outlined'}
                        color={publishSuccess === p.id ? 'success' : 'primary'}
                        startIcon={
                          publishingPlatform === p.id ? (
                            <CircularProgress size={16} />
                          ) : publishSuccess === p.id ? (
                            <CheckCircleIcon />
                          ) : (
                            p.icon
                          )
                        }
                        disabled={
                          !channelSupports ||
                          !!publishingPlatform ||
                          publishSuccess === p.id
                        }
                        onClick={() => handlePublish(p.id)}
                        title={!channelSupports ? `${p.label} non configuré sur cette chaîne` : undefined}
                      >
                        {p.label}
                        {!channelSupports && (
                          <Typography
                            component="span"
                            variant="caption"
                            sx={{ ml: 0.5, opacity: 0.6 }}
                          >
                            (non configuré)
                          </Typography>
                        )}
                      </Button>
                    )
                  })}
                </Stack>
              </Box>
            )}

            <Divider />

            {/* Actions */}
            <Stack direction="row" spacing={2} justifyContent="space-between">
              <Button
                variant="outlined"
                color="error"
                startIcon={deleting ? <CircularProgress size={16} /> : <DeleteIcon />}
                disabled={deleting}
                onClick={handleDelete}
              >
                Supprimer le projet
              </Button>
              <Stack direction="row" spacing={1}>
                <Button href={`/projects/${projectId}`} variant="outlined">
                  Voir les détails
                </Button>
                <Button
                  variant="contained"
                  startIcon={<PublishIcon />}
                  onClick={() => {
                    setStep(0)
                    setProjectId(null)
                    setVideos([])
                    setPrompt('')
                    setPublishSuccess(null)
                    advancedRef.current = false
                  }}
                >
                  Nouvelle vidéo
                </Button>
              </Stack>
            </Stack>
          </Stack>
        )}
      </Box>
    </AppShell>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', gap: 2 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 100 }}>
        {label}
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
  )
}
