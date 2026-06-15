'use client'

import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import LinearProgress from '@mui/material/LinearProgress'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import ErrorOutlineIcon from '@mui/icons-material/ErrorOutline'
import VideocamIcon from '@mui/icons-material/Videocam'
import type { CriticReport, VideoAnalysisIssue } from '@/lib/api'

const CRITERIA = [
  { key: 'rhythm', label: 'Rythme', max: 25 },
  { key: 'content_value', altKey: 'educational_value', label: 'Valeur du contenu', max: 30 },
  { key: 'visual_quality', label: 'Qualité visuelle', max: 25 },
  { key: 'structure', label: 'Accroche & structure', max: 20 },
] as const

const GEMINI_STATUS_MESSAGES: Record<string, string> = {
  missing_key: 'Clé GOOGLE_GEMINI_API_KEY manquante',
  file_not_found: 'Fichier vidéo local introuvable au moment de l\'analyse',
  error: 'Erreur lors de l\'analyse Gemini',
  no_local_path: 'Chemin local de la vidéo absent',
}

const AGENT_LABELS: Record<string, string> = {
  scenario_agent: 'Scénario',
  research_agent: 'Recherche',
  media_agent: 'Médias',
  narrator_agent: 'Narration',
  editor_agent: 'Montage',
  subtitle_agent: 'Sous-titres',
}

const SEVERITY_COLOR: Record<string, 'error' | 'warning' | 'default'> = {
  high: 'error',
  medium: 'warning',
  low: 'default',
}

const ISSUE_TYPE_LABEL: Record<string, string> = {
  subtitle: 'Sous-titres',
  visual: 'Visuel',
  audio: 'Audio',
  structure: 'Structure',
  coherence: 'Cohérence',
}

function scoreColor(value: number, max: number): 'success' | 'warning' | 'error' {
  const pct = value / max
  if (pct >= 0.75) return 'success'
  if (pct >= 0.5) return 'warning'
  return 'error'
}

function normalizeCriterionValue(raw: unknown): number | null {
  if (typeof raw === 'number' && !Number.isNaN(raw)) return raw
  if (raw && typeof raw === 'object' && 'score' in raw) {
    const score = (raw as { score: unknown }).score
    return typeof score === 'number' && !Number.isNaN(score) ? score : null
  }
  return null
}

function normalizeComments(raw: unknown): string | null {
  if (typeof raw === 'string') return raw
  if (Array.isArray(raw)) {
    const parts = raw.filter((item): item is string => typeof item === 'string')
    return parts.length > 0 ? parts.join('\n') : null
  }
  return null
}

function extractCriterionComment(raw: unknown): string | null {
  if (raw && typeof raw === 'object' && 'comments' in raw) {
    return normalizeComments((raw as { comments: unknown }).comments)
  }
  return null
}

function getCriterionValue(
  fb: Record<string, unknown>,
  key: string,
  altKey?: string,
): number | null {
  const raw = fb[key] ?? (altKey ? fb[altKey] : undefined)
  return normalizeCriterionValue(raw)
}

function buildSynthesis(report: CriticReport): { positives: string[]; negatives: string[] } {
  const fb = report.feedback as Record<string, unknown> | null
  if (!fb) return { positives: [], negatives: [] }

  const positives: string[] = []
  const negatives: string[] = []

  for (const criterion of CRITERIA) {
    const { key, label, max } = criterion
    const altKey = 'altKey' in criterion ? criterion.altKey : undefined
    const val = getCriterionValue(fb, key, altKey)
    if (val == null) continue
    const pct = val / max
    if (pct >= 0.75) positives.push(`${label} (${val}/${max})`)
    else if (pct < 0.5) negatives.push(`${label} (${val}/${max})`)
  }

  return { positives, negatives }
}

function ScoreBar({ label, value, max }: { label: string; value: number; max: number }) {
  const color = scoreColor(value, max)
  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
        <Typography variant="body2">{label}</Typography>
        <Typography variant="body2" fontWeight={600}>
          {value}/{max}
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={(value / max) * 100}
        color={color}
        sx={{ height: 8, borderRadius: 4 }}
      />
    </Box>
  )
}

function GeminiUnavailableBadge({ status }: { status: string }) {
  const message = GEMINI_STATUS_MESSAGES[status] ?? status
  return (
    <Alert severity="warning" sx={{ mt: 2 }} icon={<VideocamIcon />}>
      Analyse visuelle indisponible — {message}
    </Alert>
  )
}

function GeminiAnalysisPanel({ analysis }: { analysis: NonNullable<CriticReport['video_analysis']> }) {
  const highIssues = analysis.issues.filter((i) => i.severity === 'high')
  const mediumIssues = analysis.issues.filter((i) => i.severity === 'medium')
  const lowIssues = analysis.issues.filter((i) => i.severity === 'low')
  const orderedIssues = [...highIssues, ...mediumIssues, ...lowIssues]

  return (
    <Box sx={{ mt: 2, p: 1.5, bgcolor: 'action.hover', borderRadius: 2 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1.5 }}>
        <VideocamIcon fontSize="small" color="primary" />
        <Typography variant="body2" fontWeight={700} color="primary">
          Analyse Gemini (vision directe de la vidéo)
        </Typography>
        <Chip
          size="small"
          label={`${analysis.score}/100`}
          color={analysis.score >= 70 ? 'success' : analysis.score >= 50 ? 'warning' : 'error'}
        />
      </Box>

      <Box sx={{ display: 'flex', gap: 2, mb: 1.5, flexWrap: 'wrap' }}>
        {[
          { label: 'Cohérence visuelle', value: analysis.visual_coherence },
          { label: 'Sous-titres', value: analysis.subtitle_quality },
          { label: 'Rythme', value: analysis.rhythm },
        ].map(({ label, value }) => (
          <Box key={label} sx={{ flex: '1 1 120px' }}>
            <Typography variant="caption" color="text.secondary">{label}</Typography>
            <Typography variant="body2" fontWeight={600}>{value}/25</Typography>
          </Box>
        ))}
      </Box>

      {analysis.summary && (
        <Typography variant="body2" sx={{ mb: orderedIssues.length > 0 ? 1.5 : 0, fontStyle: 'italic' }}>
          {analysis.summary}
        </Typography>
      )}

      {orderedIssues.length > 0 && (
        <Stack spacing={0.75}>
          {orderedIssues.map((issue: VideoAnalysisIssue, i: number) => (
            <Box key={i} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
              <Chip
                label={ISSUE_TYPE_LABEL[issue.type] ?? issue.type}
                size="small"
                color={SEVERITY_COLOR[issue.severity] ?? 'default'}
                variant="outlined"
                sx={{ flexShrink: 0, mt: 0.25 }}
              />
              <Typography variant="body2" sx={{ flex: 1 }}>
                {issue.timestamp_s > 0 && (
                  <Typography component="span" variant="caption" color="text.secondary" sx={{ mr: 0.5 }}>
                    {Math.floor(issue.timestamp_s / 60)}:{String(issue.timestamp_s % 60).padStart(2, '0')}
                  </Typography>
                )}
                {issue.description}
              </Typography>
            </Box>
          ))}
        </Stack>
      )}

      {orderedIssues.length === 0 && (
        <Typography variant="body2" color="success.main">Aucun problème visuel détecté.</Typography>
      )}
    </Box>
  )
}

interface Props {
  report: CriticReport
  iterationLabel?: number
  showLastBadge?: boolean
  variant?: 'outlined' | 'elevation'
}

export default function CriticReportDetail({
  report,
  iterationLabel,
  showLastBadge = false,
  variant = 'outlined',
}: Props) {
  const fb = report.feedback as Record<string, unknown> | null
  const score = report.global_score ?? 0
  const isApproved = report.decision === 'approve'
  const { positives, negatives } = buildSynthesis(report)
  const iter = iterationLabel ?? report.iteration ?? 1
  const globalComments = fb ? normalizeComments(fb.comments) : null

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
        <Typography variant="subtitle1" fontWeight={700}>
          Itération {iter}
        </Typography>
        <Chip
          size="small"
          label={isApproved ? 'Approuvé' : 'À améliorer'}
          color={isApproved ? 'success' : 'warning'}
        />
        {showLastBadge && <Chip size="small" label="Dernière" variant="outlined" />}
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 3 }}>
        <LinearProgress
          variant="determinate"
          value={score}
          sx={{ flex: 1, height: 14, borderRadius: 7 }}
          color={score >= 70 ? 'success' : score >= 50 ? 'warning' : 'error'}
        />
        <Typography variant="h5" fontWeight={800} sx={{ minWidth: 70, textAlign: 'right' }}>
          {score}/100
        </Typography>
      </Box>

      {report.video_analysis?.analysis_status === 'ok' && (
        <GeminiAnalysisPanel analysis={report.video_analysis} />
      )}
      {report.video_analysis && report.video_analysis.analysis_status !== 'ok' && (
        <GeminiUnavailableBadge status={report.video_analysis.analysis_status ?? 'error'} />
      )}

      {fb && (
        <>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 2, mb: 1.5 }}>
            Détail par critère (évaluation Claude)
          </Typography>
          <Stack spacing={1.5} sx={{ mb: 2 }}>
            {CRITERIA.map((criterion) => {
              const { key, label, max } = criterion
              const altKey = 'altKey' in criterion ? criterion.altKey : undefined
              const raw = fb[key] ?? (altKey ? fb[altKey] : undefined)
              const val = normalizeCriterionValue(raw)
              if (val == null) return null
              const criterionComment = extractCriterionComment(raw)
              return (
                <Box key={key}>
                  <ScoreBar label={label} value={val} max={max} />
                  {criterionComment && (
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
                      {criterionComment}
                    </Typography>
                  )}
                </Box>
              )
            })}
          </Stack>
        </>
      )}

      {globalComments && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Analyse détaillée
          </Typography>
          <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
            {globalComments}
          </Typography>
        </>
      )}

      {(positives.length > 0 || negatives.length > 0) && (
        <>
          <Divider sx={{ my: 2 }} />
          <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
            {positives.length > 0 && (
              <Box sx={{ flex: 1, minWidth: 180 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                  <CheckCircleOutlineIcon fontSize="small" color="success" />
                  <Typography variant="body2" fontWeight={600} color="success.main">
                    Points forts
                  </Typography>
                </Box>
                <Stack spacing={0.5}>
                  {positives.map((p) => (
                    <Typography key={p} variant="body2">• {p}</Typography>
                  ))}
                </Stack>
              </Box>
            )}
            {negatives.length > 0 && (
              <Box sx={{ flex: 1, minWidth: 180 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, mb: 1 }}>
                  <ErrorOutlineIcon fontSize="small" color="error" />
                  <Typography variant="body2" fontWeight={600} color="error.main">
                    À améliorer
                  </Typography>
                </Box>
                <Stack spacing={0.5}>
                  {negatives.map((n) => (
                    <Typography key={n} variant="body2">• {n}</Typography>
                  ))}
                </Stack>
              </Box>
            )}
          </Box>
        </>
      )}

      {report.requested_changes && report.requested_changes.length > 0 && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            Corrections demandées
          </Typography>
          <Stack spacing={0.75}>
            {report.requested_changes.map((change, i) => (
              <Box key={i} sx={{ display: 'flex', gap: 1, alignItems: 'flex-start' }}>
                <Chip
                  label={AGENT_LABELS[change.agent] ?? change.agent}
                  size="small"
                  color="warning"
                  variant="outlined"
                  sx={{ flexShrink: 0, mt: 0.25 }}
                />
                <Typography variant="body2">{change.change_description}</Typography>
              </Box>
            ))}
          </Stack>
        </>
      )}
    </Box>
  )
}
