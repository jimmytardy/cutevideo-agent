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
import TimelineIcon from '@mui/icons-material/Timeline'
import MovieIcon from '@mui/icons-material/Movie'
import {
  authenticatedMediaUrl,
  type AgentRun,
  type BeatClipPlan,
  type EffectiveBeat,
  type MediaAsset,
  type MontagePlan,
  type SegmentMontagePlan,
} from '@/lib/api'

interface Props {
  plan: MontagePlan | null | undefined
  isRunning: boolean
  projectId: string
  mediaAssets?: MediaAsset[]
  agentRun?: AgentRun
}

const ADAPTATION_LABELS: Record<string, string> = {
  unchanged: 'Inchangé',
  merged: 'Fusionné',
  split: 'Divisé',
  added: 'Ajouté',
  removed: 'Supprimé',
}

const ADAPTATION_COLORS: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  unchanged: 'default',
  merged: 'info',
  split: 'warning',
  added: 'success',
  removed: 'error',
}

function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`
  const min = Math.floor(seconds / 60)
  const sec = Math.round(seconds % 60)
  return sec > 0 ? `${min} min ${sec}s` : `${min} min`
}

function findAssetForClip(clip: BeatClipPlan, assets: MediaAsset[] | undefined): MediaAsset | undefined {
  if (!assets?.length) return undefined
  return assets.find((a) => a.local_path && a.local_path === clip.asset_path)
    ?? assets.find((a) => {
      const srcBeat = clip.source_beat_orders[0]
      return srcBeat != null && a.beat_index === srcBeat && a.segment_order != null
    })
}

function EffectiveBeatRow({ beat }: { beat: EffectiveBeat }) {
  const adaptation = beat.adaptation || 'unchanged'
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
        <Chip
          size="small"
          label={ADAPTATION_LABELS[adaptation] ?? adaptation}
          color={ADAPTATION_COLORS[adaptation] ?? 'default'}
          variant={adaptation === 'unchanged' ? 'outlined' : 'filled'}
        />
        <Chip size="small" label={beat.visual_type} variant="outlined" />
        {beat.source_beat_orders.length > 1 && (
          <Chip
            size="small"
            label={`Sources : ${beat.source_beat_orders.join(', ')}`}
            variant="outlined"
          />
        )}
        {beat.on_screen_text && (
          <Chip size="small" label={`Écran : ${beat.on_screen_text}`} variant="outlined" />
        )}
      </Box>
      {beat.phrase_anchor && (
        <Typography variant="caption" color="text.secondary" display="block">
          Ancre : « {beat.phrase_anchor} »
        </Typography>
      )}
    </Box>
  )
}

function ClipRow({
  clip,
  projectId,
  asset,
}: {
  clip: BeatClipPlan
  projectId: string
  asset?: MediaAsset
}) {
  const duration = Math.max(0, clip.timeline_end_s - clip.timeline_start_s)
  const trimDuration = clip.source_trim_end_s != null
    ? Math.max(0, clip.source_trim_end_s - clip.source_trim_start_s)
    : null
  const previewUrl = asset
    ? authenticatedMediaUrl(`/api/v1/projects/${projectId}/media-assets/${asset.id}/stream`)
    : null
  const isVideo = clip.asset_type === 'video'

  return (
    <Box
      sx={{
        p: 1.25,
        borderRadius: 1,
        border: '1px solid',
        borderColor: 'divider',
      }}
    >
      <Box sx={{ display: 'flex', gap: 2, flexWrap: { xs: 'wrap', sm: 'nowrap' } }}>
        {previewUrl && (
          <Box
            sx={{
              width: 140,
              minWidth: 140,
              height: 79,
              borderRadius: 1,
              overflow: 'hidden',
              bgcolor: 'action.hover',
              flexShrink: 0,
            }}
          >
            {isVideo ? (
              <video
                src={previewUrl}
                controls
                style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              />
            ) : (
              <Box
                component="img"
                src={previewUrl}
                alt={`Clip beat ${clip.beat_order}`}
                sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
              />
            )}
          </Box>
        )}

        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mb: 0.75 }}>
            <Chip size="small" label={`Plan ${clip.beat_order}`} color="secondary" />
            <Chip size="small" label={clip.asset_type} variant="outlined" />
            <Chip
              size="small"
              icon={<TimelineIcon sx={{ fontSize: 14 }} />}
              label={`${formatDuration(clip.timeline_start_s)} → ${formatDuration(clip.timeline_end_s)} (${formatDuration(duration)})`}
              variant="outlined"
            />
            {clip.source_beat_orders.length > 0 && (
              <Chip
                size="small"
                label={`Beat scénario ${clip.source_beat_orders.join(', ')}`}
                variant="outlined"
              />
            )}
          </Box>

          {isVideo && trimDuration != null && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
              Découpe source : {formatDuration(clip.source_trim_start_s)} → {formatDuration(clip.source_trim_end_s!)} ({formatDuration(trimDuration)})
              {clip.trim_reason ? ` — ${clip.trim_reason}` : ''}
            </Typography>
          )}

          {clip.on_screen_text && (
            <Typography variant="body2" sx={{ fontSize: '0.8125rem' }}>
              Texte à l&apos;écran : {clip.on_screen_text}
            </Typography>
          )}

          {asset?.source && (
            <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 0.5 }}>
              Source : {asset.source}
              {asset.license ? ` · ${asset.license}` : ''}
            </Typography>
          )}
        </Box>
      </Box>
    </Box>
  )
}

function SegmentPlanDetail({
  segment,
  projectId,
  mediaAssets,
}: {
  segment: SegmentMontagePlan
  projectId: string
  mediaAssets?: MediaAsset[]
}) {
  const segAssets = mediaAssets?.filter((a) => a.segment_order === segment.segment_order) ?? []
  const segmentDuration = segment.clips.reduce(
    (sum, clip) => sum + Math.max(0, clip.timeline_end_s - clip.timeline_start_s),
    0,
  )
  const adaptations = segment.effective_beats.filter((b) => b.adaptation && b.adaptation !== 'unchanged').length

  return (
    <Accordion disableGutters variant="outlined">
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap', pr: 1 }}>
          <Typography variant="subtitle2">
            Segment {segment.segment_order}
          </Typography>
          <Chip size="small" label={`${segment.clips.length} plan${segment.clips.length > 1 ? 's' : ''}`} variant="outlined" />
          <Chip size="small" label={formatDuration(segmentDuration)} variant="outlined" />
          {adaptations > 0 && (
            <Chip size="small" label={`${adaptations} adaptation${adaptations > 1 ? 's' : ''}`} color="info" />
          )}
        </Box>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          {segment.adaptation_notes && (
            <Alert severity="info" icon={false}>
              <Typography variant="body2">{segment.adaptation_notes}</Typography>
            </Alert>
          )}

          {segment.effective_beats.length > 0 && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Beats effectifs ({segment.effective_beats.length})
              </Typography>
              <Stack spacing={1}>
                {segment.effective_beats.map((beat) => (
                  <EffectiveBeatRow key={`${segment.segment_order}-${beat.order}`} beat={beat} />
                ))}
              </Stack>
            </Box>
          )}

          {segment.clips.length > 0 && (
            <Box>
              <Typography variant="subtitle2" gutterBottom>
                Timeline montage ({segment.clips.length} clips)
              </Typography>
              <Stack spacing={1}>
                {[...segment.clips]
                  .sort((a, b) => a.timeline_start_s - b.timeline_start_s)
                  .map((clip) => (
                    <ClipRow
                      key={`${segment.segment_order}-${clip.beat_order}-${clip.timeline_start_s}`}
                      clip={clip}
                      projectId={projectId}
                      asset={findAssetForClip(clip, segAssets.length ? segAssets : mediaAssets)}
                    />
                  ))}
              </Stack>
            </Box>
          )}

          {segment.effective_beats.length === 0 && segment.clips.length === 0 && (
            <Typography variant="body2" color="text.secondary">
              Aucun plan généré pour ce segment.
            </Typography>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  )
}

function computeSummary(plan: MontagePlan) {
  const segments = plan.segments.length
  const clips = plan.segments.reduce((sum, seg) => sum + seg.clips.length, 0)
  const beats = plan.segments.reduce((sum, seg) => sum + seg.effective_beats.length, 0)
  const adaptations = plan.segments.reduce(
    (sum, seg) => sum + seg.effective_beats.filter((b) => b.adaptation && b.adaptation !== 'unchanged').length,
    0,
  )
  const duration = plan.segments.reduce(
    (sum, seg) => sum + seg.clips.reduce(
      (segSum, clip) => segSum + Math.max(0, clip.timeline_end_s - clip.timeline_start_s),
      0,
    ),
    0,
  )
  return { segments, clips, beats, adaptations, duration }
}

export default function MontagePlanDetailView({
  plan,
  isRunning,
  projectId,
  mediaAssets,
  agentRun,
}: Props) {
  if (isRunning) {
    return (
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 2 }}>
        <CircularProgress size={18} />
        <Typography color="text.secondary" variant="body2">
          Planification du montage en cours…
        </Typography>
      </Box>
    )
  }

  if (!plan || plan.segments.length === 0) {
    const runSummary = agentRun?.output_json as {
      segments?: number
      clips?: number
      beats?: number
      adaptations?: number
    } | undefined

    if (runSummary?.segments != null && runSummary.segments === 0) {
      return (
        <Alert severity="warning">
          Aucun segment planifié — vérifiez que les médias et la narration sont disponibles.
        </Alert>
      )
    }

    return (
      <Alert severity="info" icon={false}>
        Aucun plan de montage disponible pour cette itération.
      </Alert>
    )
  }

  const summary = computeSummary(plan)
  const sortedSegments = [...plan.segments].sort((a, b) => a.segment_order - b.segment_order)

  return (
    <Stack spacing={2}>
      <Box
        sx={{
          display: 'flex',
          gap: 1,
          flexWrap: 'wrap',
          alignItems: 'center',
          p: 1.5,
          borderRadius: 2,
          bgcolor: 'action.hover',
        }}
      >
        <MovieIcon color="primary" fontSize="small" />
        <Typography variant="body2" fontWeight={600}>
          Plan de montage
        </Typography>
        <Chip size="small" label={`${summary.segments} segment${summary.segments > 1 ? 's' : ''}`} />
        <Chip size="small" label={`${summary.clips} clip${summary.clips > 1 ? 's' : ''}`} variant="outlined" />
        <Chip size="small" label={`${summary.beats} beat${summary.beats > 1 ? 's' : ''}`} variant="outlined" />
        <Chip size="small" label={formatDuration(summary.duration)} variant="outlined" />
        {summary.adaptations > 0 && (
          <Chip
            size="small"
            label={`${summary.adaptations} adaptation${summary.adaptations > 1 ? 's' : ''} LLM`}
            color="info"
          />
        )}
      </Box>

      {plan.planner_notes && (
        <Alert severity="info" icon={false}>
          <Typography variant="body2">{plan.planner_notes}</Typography>
        </Alert>
      )}

      <Divider />

      <Stack spacing={1}>
        {sortedSegments.map((segment) => (
          <SegmentPlanDetail
            key={segment.segment_order}
            segment={segment}
            projectId={projectId}
            mediaAssets={mediaAssets}
          />
        ))}
      </Stack>
    </Stack>
  )
}
