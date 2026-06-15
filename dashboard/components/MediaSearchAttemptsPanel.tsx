'use client'

import Accordion from '@mui/material/Accordion'
import AccordionDetails from '@mui/material/AccordionDetails'
import AccordionSummary from '@mui/material/AccordionSummary'
import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import type { MediaRelevanceSegmentLog } from '@/lib/api'

interface SegmentAttempts {
  segmentOrder: number
  searchAttempts: MediaRelevanceSegmentLog[]
  aiAttempts: MediaRelevanceSegmentLog[]
  summary: MediaRelevanceSegmentLog | null
  validationRelaxed: boolean
}

function groupAttemptsBySegment(log: MediaRelevanceSegmentLog[]): SegmentAttempts[] {
  const bySegment = new Map<number, SegmentAttempts>()

  for (const entry of log) {
    const order = entry.segment_order
    if (!bySegment.has(order)) {
      bySegment.set(order, {
        segmentOrder: order,
        searchAttempts: [],
        aiAttempts: [],
        summary: null,
        validationRelaxed: false,
      })
    }
    const group = bySegment.get(order)!
    if (entry.validation_relaxed) {
      group.validationRelaxed = true
      continue
    }
    if (entry.total_raw_candidates != null || entry.passing_count != null) {
      group.summary = entry
      continue
    }
    if (entry.source === 'ai_generated') {
      group.aiAttempts.push(entry)
      continue
    }
    if (entry.scores?.length || entry.attempt != null) {
      group.searchAttempts.push(entry)
    }
  }

  return [...bySegment.values()].sort((a, b) => a.segmentOrder - b.segmentOrder)
}

function scoreColor(score: number): 'success' | 'warning' | 'error' | 'default' {
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'error'
}

function CandidateRow({
  title,
  score,
  reason,
  rejectionCategory,
  url,
}: {
  title?: string
  score: number
  reason?: string
  rejectionCategory?: string
  url?: string
}) {
  return (
    <Box
      sx={{
        py: 0.75,
        px: 1,
        borderRadius: 1,
        bgcolor: 'action.hover',
        mb: 0.5,
      }}
    >
      <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', alignItems: 'center', mb: 0.25 }}>
        <Chip size="small" label={`${score}/100`} color={scoreColor(score)} />
        {rejectionCategory && (
          <Chip size="small" label={rejectionCategory} variant="outlined" />
        )}
        {title && (
          <Typography variant="caption" fontWeight={600} noWrap sx={{ maxWidth: 280 }}>
            {title}
          </Typography>
        )}
      </Box>
      {reason && (
        <Typography variant="caption" color="text.secondary" display="block">
          {reason}
        </Typography>
      )}
      {url && (
        <Typography
          component="a"
          href={url}
          target="_blank"
          rel="noopener noreferrer"
          variant="caption"
          sx={{ display: 'block', wordBreak: 'break-all', color: 'primary.main' }}
        >
          {url}
        </Typography>
      )}
    </Box>
  )
}

interface Props {
  relevanceLog: MediaRelevanceSegmentLog[] | undefined
  isRunning: boolean
}

export default function MediaSearchAttemptsPanel({ relevanceLog, isRunning }: Props) {
  if (isRunning) {
    return (
      <Alert severity="info" sx={{ mt: 2 }} icon={false}>
        Le détail des tentatives sera disponible à la fin de l&apos;exécution du Media Agent.
      </Alert>
    )
  }

  if (!relevanceLog?.length) {
    return null
  }

  const segments = groupAttemptsBySegment(relevanceLog)

  return (
    <Box sx={{ mt: 3 }}>
      <Typography variant="subtitle1" sx={{ mb: 1.5 }}>
        Détail des tentatives de recherche
      </Typography>
      <Stack spacing={1}>
        {segments.map((seg) => (
          <Accordion key={seg.segmentOrder} disableGutters elevation={0} sx={{ border: '1px solid', borderColor: 'divider', borderRadius: '8px !important', '&:before': { display: 'none' } }}>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Box sx={{ display: 'flex', gap: 1, alignItems: 'center', flexWrap: 'wrap' }}>
                <Typography variant="body2" fontWeight={600}>
                  Segment {seg.segmentOrder}
                </Typography>
                {seg.summary && (
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${seg.summary.passing_count ?? 0} retenus / ${seg.summary.total_raw_candidates ?? 0} candidats`}
                  />
                )}
                {seg.summary?.niche_risk && (
                  <Chip size="small" label={`Niche ${seg.summary.niche_risk}`} color="warning" variant="outlined" />
                )}
                {seg.validationRelaxed && (
                  <Chip size="small" label="Seuil assoupli" color="info" variant="outlined" />
                )}
              </Box>
            </AccordionSummary>
            <AccordionDetails sx={{ pt: 0 }}>
              {seg.searchAttempts.length > 0 && (
                <Box sx={{ mb: 2 }}>
                  <Typography variant="caption" color="text.secondary" fontWeight={600} display="block" sx={{ mb: 1 }}>
                    Recherche stock
                  </Typography>
                  {seg.searchAttempts.map((attempt, idx) => (
                    <Box key={`search-${attempt.attempt ?? idx}`} sx={{ mb: 1.5 }}>
                      <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
                        Tentative {attempt.attempt ?? idx + 1}
                      </Typography>
                      {attempt.scores?.map((candidate, cIdx) => (
                        <CandidateRow
                          key={`${candidate.url ?? cIdx}`}
                          title={candidate.title}
                          score={candidate.score}
                          reason={candidate.reason}
                          rejectionCategory={candidate.rejection_category}
                          url={candidate.url}
                        />
                      ))}
                    </Box>
                  ))}
                </Box>
              )}

              {seg.aiAttempts.length > 0 && (
                <Box>
                  {seg.searchAttempts.length > 0 && <Divider sx={{ mb: 1.5 }} />}
                  <Typography variant="caption" color="text.secondary" fontWeight={600} display="block" sx={{ mb: 1 }}>
                    Génération IA
                  </Typography>
                  {seg.aiAttempts.map((attempt, idx) => {
                    if (attempt.phase === 'best_score_fallback') {
                      return (
                        <Alert key={`fallback-${idx}`} severity="warning" sx={{ mb: 1 }}>
                          Fallback meilleur score : {attempt.score}/100 (phase {attempt.from_phase})
                        </Alert>
                      )
                    }
                    if (attempt.generation_failed) {
                      return (
                        <Typography key={`fail-${idx}`} variant="body2" color="error" sx={{ mb: 0.5 }}>
                          {attempt.phase} — tentative {attempt.attempt} : échec génération
                        </Typography>
                      )
                    }
                    const candidate = attempt.scores?.[0]
                    return (
                      <Box key={`ai-${attempt.phase}-${attempt.attempt ?? idx}`} sx={{ mb: 1 }}>
                        <Typography variant="body2" fontWeight={600} sx={{ mb: 0.5 }}>
                          {attempt.phase} — tentative {attempt.attempt}
                        </Typography>
                        {candidate && (
                          <CandidateRow
                            title={candidate.title}
                            score={candidate.score}
                            reason={candidate.reason}
                            url={candidate.url}
                          />
                        )}
                      </Box>
                    )
                  })}
                </Box>
              )}
            </AccordionDetails>
          </Accordion>
        ))}
      </Stack>
    </Box>
  )
}
