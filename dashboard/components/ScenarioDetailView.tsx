'use client'

import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import Stack from '@mui/material/Stack'
import Divider from '@mui/material/Divider'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import RecordVoiceOverIcon from '@mui/icons-material/RecordVoiceOver'
import MusicNoteIcon from '@mui/icons-material/MusicNote'
import VolumeOffIcon from '@mui/icons-material/VolumeOff'
import type { Scenario, ScenarioSegment, VisualBeat } from '@/lib/api'

interface Props {
  scenario: Scenario | null | undefined
  projectTitle?: string | null
  isRunning?: boolean
}

const MOOD_COLORS: Record<string, 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'> = {
  energique: 'warning',
  calme: 'info',
  dramatique: 'error',
  mysterieux: 'secondary',
  inspirant: 'success',
  humoristique: 'primary',
  tension: 'error',
  revelateur: 'secondary',
}

function formatDuration(seconds: number | null | undefined): string {
  if (!seconds) return '—'
  if (seconds < 120) return `${seconds}s`
  const min = Math.floor(seconds / 60)
  const sec = seconds % 60
  return sec > 0 ? `${min} min ${sec}s` : `${min} min`
}

function segmentVoiceEnabled(seg: ScenarioSegment): boolean {
  if (seg.needs_voice === false) return false
  const text = (seg.narration_text || (seg.narration as string | undefined) || '').trim()
  return seg.needs_voice === true || Boolean(text)
}

function segmentMusicEnabled(seg: ScenarioSegment): boolean {
  if (seg.needs_music === false) return false
  if (seg.needs_music === true) return true
  return segmentVoiceEnabled(seg)
}

function FieldBlock({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box sx={{ mb: 1.5 }}>
      <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: 0.5 }}>
        {label}
      </Typography>
      <Box sx={{ mt: 0.5 }}>{children}</Box>
    </Box>
  )
}

function VisualBeatRow({ beat }: { beat: VisualBeat }) {
  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 1,
        bgcolor: 'action.hover',
        border: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.75 }}>
        <Chip size="small" label={`Beat ${beat.order}`} color="primary" />
        <Chip size="small" label={beat.visual_type} variant="outlined" />
        {beat.on_screen_text && (
          <Chip size="small" label={`Écran : ${beat.on_screen_text}`} variant="outlined" />
        )}
      </Box>
      <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
        Ancre : « {beat.phrase_anchor} »
      </Typography>
      <Typography variant="body2" sx={{ fontSize: '0.8125rem' }}>
        {beat.prompt}
      </Typography>
    </Box>
  )
}

function SegmentDetail({ seg, index }: { seg: ScenarioSegment; index: number }) {
  const order = seg.order ?? index + 1
  const hasVoice = segmentVoiceEnabled(seg)
  const hasMusic = segmentMusicEnabled(seg)
  const narration = (seg.narration_text || (seg.narration as string | undefined) || '').trim()
  const onScreen = (seg.on_screen_text || '').trim()
  const keywords = seg.search_keywords ?? []
  const sources = seg.source_hint ?? []
  const delivery = seg.delivery_style
  const emphasis = delivery?.emphasis_words ?? []
  const visualBeats = [...(seg.visual_beats ?? [])].sort((a, b) => a.order - b.order)

  return (
    <Accordion disableGutters variant="outlined">
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', pr: 1 }}>
          <Typography variant="subtitle2">
            {order}. {seg.title || `Segment ${order}`}
          </Typography>
          {seg.duration_s != null && (
            <Chip size="small" label={`${seg.duration_s}s`} variant="outlined" />
          )}
          <Chip
            size="small"
            icon={hasVoice ? <RecordVoiceOverIcon /> : <VolumeOffIcon />}
            label={hasVoice ? 'Voix' : 'Sans voix'}
            color={hasVoice ? 'success' : 'default'}
            variant={hasVoice ? 'filled' : 'outlined'}
          />
          <Chip
            size="small"
            icon={<MusicNoteIcon />}
            label={hasMusic ? 'Musique' : 'Sans musique'}
            color={hasMusic ? 'primary' : 'default'}
            variant={hasMusic ? 'filled' : 'outlined'}
          />
          {seg.mood && (
            <Chip size="small" label={seg.mood} color={MOOD_COLORS[seg.mood] ?? 'default'} />
          )}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={0} divider={<Divider flexItem sx={{ my: 1.5 }} />}>
          {narration && (
            <FieldBlock label="Texte de la voix">
              <Typography variant="body2" sx={{ lineHeight: 1.75, whiteSpace: 'pre-wrap' }}>
                {narration}
              </Typography>
            </FieldBlock>
          )}

          {onScreen && (
            <FieldBlock label="Texte à l'écran">
              <Typography variant="body2" sx={{ lineHeight: 1.6 }}>
                {onScreen}
              </Typography>
            </FieldBlock>
          )}

          <FieldBlock label="Audio source du clip">
            <Chip
              size="small"
              label={
                seg.strip_source_audio === false
                  ? 'Conservé (sons ambiants)'
                  : 'Coupé (muet ou voix/musique seule)'
              }
              variant="outlined"
            />
          </FieldBlock>

          {keywords.length > 0 && (
            <FieldBlock label="Mots-clés recherche médias">
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                {keywords.map((kw) => (
                  <Chip key={kw} size="small" label={kw} variant="outlined" />
                ))}
              </Box>
            </FieldBlock>
          )}

          {sources.length > 0 && (
            <FieldBlock label="Sources médias suggérées">
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                {sources.map((src) => (
                  <Chip key={src} size="small" label={src} color="primary" variant="outlined" />
                ))}
              </Box>
            </FieldBlock>
          )}

          {seg.hook_type && (
            <FieldBlock label="Type de hook">
              <Chip size="small" label={seg.hook_type} />
            </FieldBlock>
          )}

          {delivery && (
            <FieldBlock label="Style de delivery (TTS)">
              <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                {delivery.pace && <Chip size="small" label={`Rythme : ${delivery.pace}`} variant="outlined" />}
                {delivery.emotion && <Chip size="small" label={`Émotion : ${delivery.emotion}`} variant="outlined" />}
                {delivery.azure_style && (
                  <Chip size="small" label={`Style Azure : ${delivery.azure_style}`} variant="outlined" />
                )}
              </Box>
              {emphasis.length > 0 && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 0.75, display: 'block' }}>
                  Mots accentués : {emphasis.join(', ')}
                </Typography>
              )}
            </FieldBlock>
          )}

          {visualBeats.length > 0 && (
            <FieldBlock label={`Storyboard visuel (${visualBeats.length} beats)`}>
              <Stack spacing={1}>
                {visualBeats.map((beat) => (
                  <VisualBeatRow key={beat.order} beat={beat} />
                ))}
              </Stack>
            </FieldBlock>
          )}

          {seg.visual_suggestion && (
            <FieldBlock label="Suggestion visuelle (legacy)">
              <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
                {seg.visual_suggestion as string}
              </Typography>
            </FieldBlock>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

export default function ScenarioDetailView({ scenario, projectTitle, isRunning }: Props) {
  if (isRunning) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 2 }}>
        <CircularProgress size={18} />
        <Typography color="text.secondary" variant="body2">
          Scénario en cours de génération…
        </Typography>
      </Box>
    )
  }

  if (!scenario) {
    return (
      <Alert severity="info" icon={false}>
        Le scénario n&apos;a pas encore été généré.
      </Alert>
    )
  }

  const segments = [...(scenario.segments ?? [])].sort(
    (a, b) => (a.order ?? 0) - (b.order ?? 0),
  )
  const withVoice = segments.filter((s) => segmentVoiceEnabled(s)).length
  const withMusic = segments.filter((s) => segmentMusicEnabled(s)).length
  const totalBeats = segments.reduce((acc, s) => acc + (s.visual_beats?.length ?? 0), 0)

  return (
    <Box>
      <Box sx={{ mb: 2 }}>
        {projectTitle && (
          <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 0.5 }}>
            {projectTitle}
          </Typography>
        )}
        <Typography variant="body2" color="text.secondary">
          {segments.length} segment{segments.length > 1 ? 's' : ''}
          {scenario.total_duration_s ? ` · ${formatDuration(scenario.total_duration_s)}` : ''}
          {scenario.iteration ? ` · itération ${scenario.iteration}` : ''}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {withVoice} avec voix · {segments.length - withVoice} sans voix · {withMusic} avec musique
          {totalBeats > 0 ? ` · ${totalBeats} visual beats` : ''}
        </Typography>
      </Box>

      <Stack spacing={1}>
        {segments.map((seg, i) => (
          <SegmentDetail key={`${seg.order ?? i}-${i}`} seg={seg} index={i} />
        ))}
      </Stack>
    </Box>
  )
}
