'use client'

import { useEffect, useState } from 'react'
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
import CircularProgress from '@mui/material/CircularProgress'
import Alert from '@mui/material/Alert'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import AccessTimeIcon from '@mui/icons-material/AccessTime'
import MovieIcon from '@mui/icons-material/Movie'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import { PageContainer, PageHeader } from '@/components/layout'
import {
  createProject,
  fetchChannels,
  runPipeline,
  checkTopicSimilarity,
  type Channel,
  type SimilarTopic,
} from '@/lib/api'

type VideoType = 'short' | 'long'

const STEPS = ['Configurer', 'Estimation', 'Lancement']

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
  const [shortDurationSeconds, setShortDurationSeconds] = useState(60)

  // Similarity check
  const [similarTopics, setSimilarTopics] = useState<SimilarTopic[]>([])
  const [checkingDuplicate, setCheckingDuplicate] = useState(false)

  // Step 2 — projet lancé
  const [projectId, setProjectId] = useState<string | null>(null)
  const [launching, setLaunching] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)

  useEffect(() => {
    if (!channelId || prompt.trim().length < 10) {
      setSimilarTopics([])
      return
    }
    const timeout = setTimeout(async () => {
      setCheckingDuplicate(true)
      try {
        const result = await checkTopicSimilarity(channelId, prompt.trim())
        setSimilarTopics(result.similar_topics)
      } catch {
        // non-bloquant
      } finally {
        setCheckingDuplicate(false)
      }
    }, 600)
    return () => clearTimeout(timeout)
  }, [channelId, prompt])

  const selectedChannel = channels?.find((c) => c.id === channelId)
  const estimatedMin = estimateMinutes(videoType, videoType === 'short' ? shortDurationSeconds : durationSeconds)
  const durationLabel =
    videoType === 'short'
      ? `${shortDurationSeconds} sec (Short 9:16)`
      : `${Math.round(durationSeconds / 60)} min`

  const targetSeconds = videoType === 'short' ? shortDurationSeconds : durationSeconds

  const handleLaunch = async () => {
    if (!channelId || !prompt.trim()) return
    setLaunching(true)
    setCreateError(null)
    try {
      const config =
        videoType === 'short' ? { format: 'short_standalone' } : undefined
      const created = await createProject(channelId, prompt.trim(), targetSeconds, config)
      setProjectId(created.id)
      await runPipeline(created.id)
      setStep(2)
    } catch (e) {
      setCreateError(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      setLaunching(false)
    }
  }

  return (
    <PageContainer maxWidth="md">
      <PageHeader
        title="Créer une vidéo"
        description="Configurez votre production, estimez le temps de génération et lancez le pipeline."
      />

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

            {checkingDuplicate && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <CircularProgress size={14} />
                <Typography variant="caption" color="text.secondary">Vérification des doublons…</Typography>
              </Box>
            )}

            {similarTopics.length > 0 && (
              <Alert severity="warning">
                <Typography variant="body2" fontWeight={600} gutterBottom>
                  {similarTopics.length} vidéo{similarTopics.length > 1 ? 's' : ''} similaire{similarTopics.length > 1 ? 's' : ''} déjà réalisée{similarTopics.length > 1 ? 's' : ''} sur cette chaîne
                </Typography>
                {similarTopics.map((t, i) => (
                  <Typography key={i} variant="caption" display="block">
                    • {t.title || t.theme || '(sans titre)'}
                    {t.created_at ? ` — ${new Date(t.created_at).toLocaleDateString('fr-FR')}` : ''}
                  </Typography>
                ))}
              </Alert>
            )}

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
                <ToggleButton value="short">Short 9:16</ToggleButton>
                <ToggleButton value="long">Vidéo longue</ToggleButton>
              </ToggleButtonGroup>
            </Box>

            {videoType === 'short' && (
              <Box>
                <Typography variant="body2" gutterBottom>
                  Durée cible : <strong>{shortDurationSeconds} s</strong>
                </Typography>
                <Slider
                  value={shortDurationSeconds}
                  onChange={(_, v) => setShortDurationSeconds(v as number)}
                  min={45}
                  max={90}
                  step={15}
                  marks={[
                    { value: 45, label: '45s' },
                    { value: 60, label: '60s' },
                    { value: 90, label: '90s' },
                  ]}
                />
              </Box>
            )}

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
              sx={{
                p: 3,
                borderRadius: 2,
                borderColor: 'primary.main',
                bgcolor: (t) =>
                  t.palette.mode === 'light'
                    ? `${t.palette.primary.main}14`
                    : 'action.selected',
              }}
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

        {/* ── Step 2 : Projet lancé ── */}
        {step === 2 && projectId && (
          <Stack spacing={3} alignItems="center" sx={{ textAlign: 'center', py: 4 }}>
            <RocketLaunchIcon sx={{ fontSize: 56, color: 'primary.main' }} />
            <Typography variant="h6">Projet créé — génération lancée</Typography>
            <Typography variant="body2" color="text.secondary" sx={{ maxWidth: 420 }}>
              Le pipeline tourne en arrière-plan (estimation ~{estimatedMin} min).
              Suivez l&apos;avancement, les agents et la vidéo finale depuis la page du projet.
            </Typography>
            <Stack direction="row" spacing={2} sx={{ mt: 1 }}>
              <Button
                variant="contained"
                size="large"
                href={`/projects/${projectId}`}
              >
                Voir l&apos;avancement du projet
              </Button>
              <Button
                variant="outlined"
                onClick={() => {
                  setStep(0)
                  setProjectId(null)
                  setPrompt('')
                  setCreateError(null)
                }}
              >
                Nouvelle vidéo
              </Button>
            </Stack>
          </Stack>
        )}
    </PageContainer>
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
