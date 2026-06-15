'use client'

import { useMemo } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  fetchProjectMediaValidation,
  type BeatValidationResolved,
  type MediaValidationBrief,
} from '@/lib/api'

interface Props {
  projectId: string
  projectStatus: string
}

function chipsFromList(items: string[], color: 'success' | 'error' | 'warning') {
  if (!items.length) return <Typography variant="body2" color="text.secondary">—</Typography>
  return (
    <Stack direction="row" flexWrap="wrap" gap={0.5}>
      {items.map((item) => (
        <Chip key={item} label={item} size="small" color={color} variant="outlined" />
      ))}
    </Stack>
  )
}

function BeatValidationRow({ beat }: { beat: BeatValidationResolved }) {
  const isClassic = beat.beat_order == null
  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 1,
        border: '1px solid',
        borderColor: 'divider',
        bgcolor: 'action.hover',
      }}
    >
      <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', alignItems: 'center', mb: 1 }}>
        {isClassic ? (
          <Chip size="small" label="Mode segment classique" variant="outlined" />
        ) : (
          <>
            <Chip size="small" label={`Beat ${beat.beat_order}`} color="primary" variant="outlined" />
            {beat.visual_type && (
              <Chip size="small" label={beat.visual_type} variant="outlined" />
            )}
          </>
        )}
        <Chip size="small" label={`seuil ${beat.min_relevance_score}`} />
        {beat.layers.map((layer) => (
          <Chip key={layer} size="small" label={layer} variant="outlined" sx={{ fontSize: '0.7rem' }} />
        ))}
      </Box>

      {!isClassic && beat.phrase_anchor && (
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
          Ancre : « {beat.phrase_anchor} »
        </Typography>
      )}
      {!isClassic && beat.prompt && (
        <Typography variant="body2" sx={{ fontSize: '0.8125rem', mb: 1 }}>
          {beat.prompt}
        </Typography>
      )}

      <Box sx={{ mb: 1 }}>
        <Typography variant="caption" color="text.secondary">Doit montrer</Typography>
        {chipsFromList(beat.must_include, 'success')}
      </Box>
      <Box sx={{ mb: beat.validation_prompt ? 1 : 0 }}>
        <Typography variant="caption" color="text.secondary">Ne doit pas montrer</Typography>
        {chipsFromList(beat.must_exclude, 'error')}
      </Box>
      {beat.validation_prompt && (
        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', fontSize: '0.8125rem' }}>
          {beat.validation_prompt}
        </Typography>
      )}
    </Box>
  )
}

export default function MediaValidationPanel({ projectId, projectStatus }: Props) {
  const { data: brief, isLoading, error } = useSWR<MediaValidationBrief>(
    `/api/v1/projects/${projectId}/media-validation`,
    () => fetchProjectMediaValidation(projectId),
    { refreshInterval: projectStatus === 'running' ? 5000 : 0 },
  )

  const beatsBySegment = useMemo(() => {
    if (!brief?.resolved_beats?.length) return []
    const map = new Map<number, { title: string; beats: BeatValidationResolved[] }>()
    for (const beat of brief.resolved_beats) {
      const existing = map.get(beat.segment_order)
      if (existing) {
        existing.beats.push(beat)
      } else {
        map.set(beat.segment_order, {
          title: beat.segment_title,
          beats: [beat],
        })
      }
    }
    return [...map.entries()].sort(([a], [b]) => a - b)
  }, [brief?.resolved_beats])

  if (isLoading) {
    return <CircularProgress size={24} sx={{ my: 2 }} />
  }

  if (error || !brief) {
    return (
      <Alert severity="info" sx={{ my: 2 }}>
        Brief de validation disponible après génération du scénario.
      </Alert>
    )
  }

  const hasResolvedBeats = beatsBySegment.length > 0

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2, flexWrap: 'wrap' }}>
        <Typography variant="h6">Validation média</Typography>
        <Chip label={brief.source} size="small" variant="outlined" />
        <Chip
          label={`niche: ${brief.niche_risk}`}
          size="small"
          color={brief.niche_risk === 'high' ? 'warning' : 'default'}
        />
        <Chip label={`seuil défaut ${brief.min_relevance_score}`} size="small" />
      </Box>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Critères générés automatiquement par le scénariste — lecture seule.
      </Typography>

      <Typography variant="subtitle2" gutterBottom>
        Sujet précis : {brief.subject_entity || '—'} ({brief.subject_type})
      </Typography>

      <Accordion disableGutters sx={{ mb: 2, '&:before': { display: 'none' } }}>
        <AccordionSummary expandIcon={<ExpandMoreIcon />}>
          <Typography variant="subtitle2">Règles communes (projet)</Typography>
        </AccordionSummary>
        <AccordionDetails>
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary">Doit montrer</Typography>
            {chipsFromList(brief.must_include, 'success')}
          </Box>
          <Box sx={{ mb: 2 }}>
            <Typography variant="caption" color="text.secondary">Ne doit pas montrer</Typography>
            {chipsFromList(brief.must_exclude, 'error')}
          </Box>
          {brief.ambiguity_warnings.length > 0 && (
            <Box sx={{ mb: 2 }}>
              <Typography variant="caption" color="text.secondary">Pièges connus</Typography>
              {chipsFromList(brief.ambiguity_warnings, 'warning')}
            </Box>
          )}
          {brief.validation_prompt && (
            <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
              {brief.validation_prompt}
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>

      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        Critères par beat
      </Typography>

      {!hasResolvedBeats && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Aucun beat résolu — le scénario n&apos;a peut-être pas encore de visual beats.
        </Alert>
      )}

      {beatsBySegment.map(([segmentOrder, { title, beats }]) => (
        <Accordion key={segmentOrder} disableGutters variant="outlined" sx={{ mb: 1 }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />}>
            <Typography variant="body2">
              #{segmentOrder} {title}
              <Typography component="span" variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                ({beats.length} {beats.length > 1 ? 'entrées' : 'entrée'})
              </Typography>
            </Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1}>
              {beats.map((beat) => (
                <BeatValidationRow
                  key={`${beat.segment_order}-${beat.beat_order ?? 'classic'}`}
                  beat={beat}
                />
              ))}
            </Stack>
          </AccordionDetails>
        </Accordion>
      ))}
    </Box>
  )
}
