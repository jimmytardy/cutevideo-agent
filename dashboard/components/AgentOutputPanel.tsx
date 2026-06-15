'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import Stack from '@mui/material/Stack'
import Tooltip from '@mui/material/Tooltip'
import LinearProgress from '@mui/material/LinearProgress'
import CriticReportDetail from './CriticReportDetail'
import ScenarioDetailView from './ScenarioDetailView'
import MediaSearchAttemptsPanel from './MediaSearchAttemptsPanel'
import {
  fetcher,
  mediaProgressUrl,
  type AgentRun,
  type MediaAsset,
  type MediaProgress,
  type MediaRelevanceSegmentLog,
  type Video,
  type Scenario,
  type AudioFile,
  type CriticReport,
  type ResearchBrief,
} from '@/lib/api'
import {
  AGENT_LABELS,
  getAgentRunForStep,
  getCriticReportForIteration,
  type PipelineSelection,
} from '@/lib/pipeline'

const VIDEO_TYPE_LABELS: Record<string, string> = {
  long: 'Vidéo longue',
  short_master: 'Master shorts',
}

interface Props {
  projectId: string
  selection: PipelineSelection
  agentRuns: AgentRun[]
  criticReports: CriticReport[]
}

function Running() {
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, py: 2 }}>
      <CircularProgress size={18} />
      <Typography color="text.secondary" variant="body2">En cours d&apos;exécution…</Typography>
    </Box>
  )
}

function Empty({ message }: { message?: string }) {
  return (
    <Alert severity="info" icon={false}>
      {message ?? 'Aucun résultat disponible pour cet agent.'}
    </Alert>
  )
}

function ScenarioView({ scenario, isRunning }: { scenario: Scenario | null | undefined; isRunning: boolean }) {
  return <ScenarioDetailView scenario={scenario} isRunning={isRunning} />
}

function scoreChipColor(score: number): 'success' | 'warning' | 'error' | 'default' {
  if (score >= 80) return 'success'
  if (score >= 60) return 'warning'
  return 'error'
}

function resolveAssetRelevance(
  asset: MediaAsset,
  relevanceLog: MediaRelevanceSegmentLog[] | undefined,
): { score: number | null; reason: string | null } {
  if (asset.relevance_score != null) {
    return { score: asset.relevance_score, reason: asset.relevance_reason }
  }
  if (!relevanceLog?.length) return { score: null, reason: null }

  const segmentLogs = relevanceLog.filter((entry) => entry.segment_order === asset.segment_order)
  for (const entry of segmentLogs) {
    const match = entry.scores?.find(
      (s) =>
        (asset.source_url && s.url && s.url === asset.source_url)
        || (asset.local_path && s.url && s.url === asset.local_path),
    )
    if (match) return { score: match.score, reason: match.reason }
  }
  return { score: null, reason: null }
}

const LIBRARY_STATUS_LABELS: Record<string, { label: string; color: 'default' | 'success' | 'warning' | 'info' }> = {
  selected: { label: 'Montage', color: 'success' },
  pool: { label: 'Bibliothèque', color: 'info' },
  rejected: { label: 'Rejeté', color: 'default' },
}

function MediaProgressBar({ progress, isRunning }: { progress: MediaProgress | undefined; isRunning: boolean }) {
  if (!progress || progress.total === 0) return null
  return (
    <Box sx={{ mb: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
        <Typography variant="body2" color="text.secondary">
          {progress.found} / {progress.total} médias ({progress.percent} %)
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {progress.segments_done} / {progress.segments_total} segments
        </Typography>
      </Box>
      <LinearProgress
        variant="determinate"
        value={Math.min(100, progress.percent)}
        sx={{ height: 8, borderRadius: 1 }}
      />
      {isRunning && (
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1 }}>
          <CircularProgress size={14} />
          <Typography variant="caption" color="text.secondary">
            Recherche en cours…
          </Typography>
        </Box>
      )}
    </Box>
  )
}

function MediaAssetsView({
  assets,
  isRunning,
  projectId,
  agentRun,
  iteration,
  progress,
}: {
  assets: MediaAsset[] | undefined
  isRunning: boolean
  projectId: string
  agentRun?: AgentRun
  iteration?: number
  progress?: MediaProgress
}) {
  const relevanceLog = (
    agentRun?.output_json as { relevance_scores?: MediaRelevanceSegmentLog[] } | undefined
  )?.relevance_scores

  const iterationFilter = iteration ?? progress?.iteration
  const filteredAssets = (assets ?? []).filter((asset) => {
    if (iterationFilter == null) return asset.library_status === 'selected' || asset.selected
    return (
      asset.iteration === iterationFilter
      && (asset.library_status === 'selected' || asset.selected)
    )
  })

  const sorted = [...filteredAssets].sort((a, b) => {
    const seg = (a.segment_order ?? 0) - (b.segment_order ?? 0)
    if (seg !== 0) return seg
    return (a.beat_index ?? 0) - (b.beat_index ?? 0)
  })

  const selectedCount = sorted.length
  const poolCount = (assets ?? []).filter((a) => a.library_status === 'pool').length

  if (!isRunning && sorted.length === 0) {
    return (
      <>
        <MediaProgressBar progress={progress} isRunning={false} />
        <Empty message="Aucun média collecté." />
        <MediaSearchAttemptsPanel relevanceLog={relevanceLog} isRunning={false} />
      </>
    )
  }

  return (
    <Stack spacing={1}>
      <MediaProgressBar progress={progress} isRunning={isRunning} />
      {!isRunning && (selectedCount > 0 || poolCount > 0) && (
        <Typography variant="caption" color="text.secondary">
          {selectedCount} en montage · {poolCount} en bibliothèque (réutilisables)
        </Typography>
      )}
      {sorted.map((a) => {
        const { score, reason } = resolveAssetRelevance(a, relevanceLog)
        const previewUrl = `/api/v1/projects/${projectId}/media-assets/${a.id}/stream`
        const isVideo = a.asset_type === 'video'

        return (
          <Card key={a.id} variant="outlined">
            <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
              <Box sx={{ display: 'flex', gap: 2, flexWrap: { xs: 'wrap', sm: 'nowrap' } }}>
                <Box
                  sx={{
                    width: 160,
                    minWidth: 160,
                    height: 90,
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
                      alt={a.attribution ?? `Segment ${a.segment_order ?? '?'}`}
                      sx={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                      onError={(e) => {
                        const img = e.currentTarget
                        if (a.source_url && img.src !== a.source_url) {
                          img.src = a.source_url
                        }
                      }}
                    />
                  )}
                </Box>

                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center', mb: 0.5 }}>
                    {a.segment_order != null && <Chip size="small" label={`Seg. ${a.segment_order}`} />}
                    {a.beat_index != null && (
                      <Chip size="small" label={`Beat ${a.beat_index}`} color="secondary" variant="outlined" />
                    )}
                    {a.visual_type && (
                      <Chip size="small" label={a.visual_type} variant="outlined" />
                    )}
                    {a.library_status && (
                      <Chip
                        size="small"
                        label={LIBRARY_STATUS_LABELS[a.library_status]?.label ?? a.library_status}
                        color={LIBRARY_STATUS_LABELS[a.library_status]?.color ?? 'default'}
                        variant={a.library_status === 'selected' ? 'filled' : 'outlined'}
                      />
                    )}
                    {a.asset_type && <Chip size="small" label={a.asset_type} color="primary" variant="outlined" />}
                    {a.source && <Chip size="small" label={a.source} variant="outlined" />}
                    {a.license && <Chip size="small" label={a.license} variant="outlined" />}
                    {score != null ? (
                      <Tooltip title={reason ?? 'Score de pertinence Gemini'}>
                        <Chip
                          size="small"
                          label={`Gemini ${score}/100`}
                          color={scoreChipColor(score)}
                        />
                      </Tooltip>
                    ) : (
                      <Chip size="small" label="Score Gemini —" variant="outlined" />
                    )}
                  </Box>
                  {reason && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                      {reason}
                    </Typography>
                  )}
                  {a.generation_prompt && (
                    <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 0.5 }}>
                      Prompt : {a.generation_prompt}
                    </Typography>
                  )}
                  {a.attribution && (
                    <Typography variant="caption" color="text.secondary" display="block">
                      {a.attribution}
                    </Typography>
                  )}
                  {a.source_url && (
                    <Typography
                      component="a"
                      href={a.source_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      variant="caption"
                      sx={{ display: 'block', mt: 0.25, wordBreak: 'break-all', color: 'primary.main' }}
                    >
                      {a.source_url}
                    </Typography>
                  )}
                </Box>
              </Box>
            </CardContent>
          </Card>
        )
      })}
      <MediaSearchAttemptsPanel relevanceLog={relevanceLog} isRunning={isRunning} />
    </Stack>
  )
}

function AudioFilesView({
  files,
  isRunning,
  agentRun,
}: {
  files: AudioFile[] | undefined
  isRunning: boolean
  agentRun?: AgentRun
}) {
  if (isRunning) return <Running />
  const audioCount = (agentRun?.output_json as { audio_count?: number } | undefined)?.audio_count
  if (audioCount === 0) {
    return (
      <Alert severity="error">
        Narration : 0 fichier audio généré — vérifiez la configuration TTS (Azure ou edge-tts).
      </Alert>
    )
  }
  if (!files || files.length === 0) return <Empty message="Aucun fichier audio généré." />
  return (
    <Stack spacing={1.5}>
      {files.map((f) => (
        <Card key={f.id} variant="outlined">
          <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
            <Box sx={{ display: 'flex', gap: 1, mb: f.transcript ? 1 : 0, flexWrap: 'wrap', alignItems: 'center' }}>
              {f.segment_order != null && <Chip size="small" label={`Seg. ${f.segment_order}`} />}
              {f.voice && <Chip size="small" label={f.voice} color="primary" variant="outlined" />}
              {f.tts_engine && <Chip size="small" label={f.tts_engine} variant="outlined" />}
              {f.duration_s != null && (
                <Typography variant="caption" color="text.secondary">{f.duration_s.toFixed(1)}s</Typography>
              )}
              {f.word_timestamps && f.word_timestamps.length > 0 && (
                <Chip size="small" label={`Whisper ${f.word_timestamps.length} mots`} color="success" variant="outlined" />
              )}
            </Box>
            {f.transcript && (
              <Typography variant="body2" sx={{ lineHeight: 1.7 }}>{f.transcript}</Typography>
            )}
          </CardContent>
        </Card>
      ))}
    </Stack>
  )
}

function VideoView({
  videos,
  isRunning,
  emptyMessage,
  projectId,
  iteration,
}: {
  videos: Video[] | undefined
  isRunning: boolean
  emptyMessage?: string
  projectId: string
  iteration?: number
}) {
  const [playingId, setPlayingId] = useState<string | null>(null)

  if (isRunning) return <Running />

  const filtered = iteration != null
    ? videos?.filter((v) => v.iteration === iteration)
    : videos

  if (!filtered || filtered.length === 0) {
    return <Empty message={emptyMessage ?? 'Aucune vidéo générée.'} />
  }

  return (
    <Stack spacing={1}>
      {filtered.map((v) => (
        <Card key={v.id} variant="outlined">
          <CardContent sx={{ py: 1.5, '&:last-child': { pb: 1.5 } }}>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', alignItems: 'center' }}>
              <Chip
                size="small"
                label={VIDEO_TYPE_LABELS[v.video_type ?? ''] ?? (v.video_type ?? 'Vidéo')}
                color="primary"
              />
              <Chip
                size="small"
                label={v.status}
                color={v.status === 'approved' ? 'success' : 'default'}
                variant="outlined"
              />
              {v.duration_s != null && (
                <Typography variant="caption" color="text.secondary">
                  {Math.round(v.duration_s)}s
                </Typography>
              )}
              <Box sx={{ flex: 1 }} />
              <Button
                size="small"
                variant={playingId === v.id ? 'outlined' : 'contained'}
                onClick={() => setPlayingId(playingId === v.id ? null : v.id)}
              >
                {playingId === v.id ? 'Fermer' : '▶ Lire'}
              </Button>
            </Box>
            {playingId === v.id && (
              <Box sx={{ mt: 1.5 }}>
                <video
                  controls
                  style={{ width: '100%', borderRadius: 4, display: 'block' }}
                  src={`/api/v1/projects/${projectId}/videos/${v.id}/stream`}
                />
              </Box>
            )}
          </CardContent>
        </Card>
      ))}
    </Stack>
  )
}

function ResearchView({
  brief,
  isRunning,
}: {
  brief: ResearchBrief | null | undefined
  isRunning: boolean
}) {
  if (isRunning) return <Running />
  if (!brief || !brief.key_facts?.length) {
    return <Empty message="Aucun brief de recherche disponible." />
  }
  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="subtitle2" gutterBottom>Entité sujet</Typography>
        <Typography variant="body2">{brief.subject_entity}</Typography>
        <Chip size="small" label={`Confiance ${(brief.confidence * 100).toFixed(0)}%`} sx={{ mt: 1, mr: 1 }} />
        <Chip size="small" label={`Niche ${brief.niche_risk}`} variant="outlined" />
      </Box>
      <Divider />
      <Box>
        <Typography variant="subtitle2" gutterBottom>Faits clés</Typography>
        <Stack component="ul" spacing={0.5} sx={{ pl: 2, m: 0 }}>
          {brief.key_facts.map((fact, i) => (
            <Typography key={i} component="li" variant="body2">{fact}</Typography>
          ))}
        </Stack>
      </Box>
      {brief.common_misconceptions?.length > 0 && (
        <Box>
          <Typography variant="subtitle2" gutterBottom>Idées reçues</Typography>
          <Stack component="ul" spacing={0.5} sx={{ pl: 2, m: 0 }}>
            {brief.common_misconceptions.map((m, i) => (
              <Typography key={i} component="li" variant="body2">{m}</Typography>
            ))}
          </Stack>
        </Box>
      )}
      {brief.sources?.length > 0 && (
        <Box>
          <Typography variant="subtitle2" gutterBottom>Sources</Typography>
          <Stack spacing={0.5}>
            {brief.sources.map((src, i) => (
              <Typography key={i} variant="body2">
                {src.title}
                {src.url ? ` — ${src.url}` : ''}
              </Typography>
            ))}
          </Stack>
        </Box>
      )}
    </Stack>
  )
}

function JsonOutputView({ agentRun, isRunning }: { agentRun: AgentRun | undefined; isRunning: boolean }) {
  if (isRunning) return <Running />
  if (!agentRun?.output_json) return <Empty />
  return (
    <Box
      component="pre"
      sx={{
        bgcolor: 'action.hover',
        p: 2,
        borderRadius: 2,
        overflow: 'auto',
        fontSize: 12,
        fontFamily: 'monospace',
        maxHeight: 400,
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      }}
    >
      {JSON.stringify(agentRun.output_json, null, 2)}
    </Box>
  )
}

const VIDEO_STEPS = ['editor_agent', 'subtitle_agent', 'short_editor_agent']
const MEDIA_AUDIO_STEPS = ['media_agent', 'narrator_agent']

export default function AgentOutputPanel({
  projectId,
  selection,
  agentRuns,
  criticReports,
}: Props) {
  const { step, iteration } = selection
  const isMediaOrAudio = MEDIA_AUDIO_STEPS.includes(step)
  const needsLatestArtifacts = isMediaOrAudio && iteration != null && iteration > 1

  const agentRun = iteration != null
    ? getAgentRunForStep(agentRuns, step, iteration)
    : getAgentRunForStep(agentRuns, step)

  const isRunning = agentRun?.status === 'running'

  const { data: researchBrief } = useSWR<ResearchBrief | null>(
    step === 'research_agent' ? `/api/v1/projects/${projectId}/research` : null,
    fetcher,
    { refreshInterval: 3000 },
  )
  const { data: scenario } = useSWR<Scenario | null>(
    step === 'scenario_agent' ? `/api/v1/projects/${projectId}/scenario` : null,
    fetcher,
    { refreshInterval: 3000 },
  )
  const { data: mediaAssets } = useSWR<MediaAsset[]>(
    step === 'media_agent' ? `/api/v1/projects/${projectId}/media-assets` : null,
    fetcher,
    { refreshInterval: step === 'media_agent' && isRunning ? 5000 : 3000 },
  )
  const { data: mediaProgress } = useSWR<MediaProgress>(
    step === 'media_agent' && (isRunning || agentRun?.status === 'success')
      ? mediaProgressUrl(projectId, iteration ?? undefined)
      : null,
    fetcher,
    { refreshInterval: isRunning ? 5000 : 0 },
  )
  const { data: audioFiles } = useSWR<AudioFile[]>(
    step === 'narrator_agent' ? `/api/v1/projects/${projectId}/audio` : null,
    fetcher,
    { refreshInterval: 3000 },
  )
  const { data: videos } = useSWR<Video[]>(
    VIDEO_STEPS.includes(step) ? `/api/v1/projects/${projectId}/videos` : null,
    fetcher,
    { refreshInterval: 3000 },
  )

  const title = iteration != null
    ? `${AGENT_LABELS[step] ?? step} — itération ${iteration}`
    : AGENT_LABELS[step] ?? step

  const criticReport = step === 'critic_agent' && iteration != null
    ? getCriticReportForIteration(criticReports, iteration)
    : undefined

  return (
    <Box>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5, mb: 2 }}>
        <Typography variant="h6">{title}</Typography>
        {isRunning && <Chip size="small" label="En cours" color="info" />}
        {agentRun?.status === 'failed' && <Chip size="small" label="Échoué" color="error" />}
        {agentRun?.status === 'success' && <Chip size="small" label="Terminé" color="success" />}
      </Box>

      {agentRun?.status === 'failed' && agentRun.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          <Typography variant="body2" sx={{ fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
            {agentRun.error}
          </Typography>
        </Alert>
      )}

      {needsLatestArtifacts && (
        <Alert severity="info" sx={{ mb: 2 }} icon={false}>
          Les vidéos sont conservées par itération. Les médias actifs et la bibliothèque (pool) reflètent l&apos;état en base — les beats réutilisés depuis le pool ne déclenchent pas de regénération IA.
        </Alert>
      )}

      {step === 'research_agent' && (
        <ResearchView brief={researchBrief} isRunning={isRunning} />
      )}
      {step === 'scenario_agent' && (
        <ScenarioView scenario={scenario} isRunning={isRunning} />
      )}
      {step === 'media_agent' && (
        <MediaAssetsView
          assets={mediaAssets}
          isRunning={isRunning}
          projectId={projectId}
          agentRun={agentRun}
          iteration={iteration}
          progress={mediaProgress}
        />
      )}
      {step === 'narrator_agent' && (
        <AudioFilesView files={audioFiles} isRunning={isRunning} agentRun={agentRun} />
      )}
      {(step === 'editor_agent' || step === 'subtitle_agent') && (
        <VideoView
          videos={videos?.filter((v) => ['long', 'short_master'].includes(v.video_type ?? ''))}
          isRunning={isRunning}
          emptyMessage="Aucune vidéo principale générée pour cette itération."
          projectId={projectId}
          iteration={iteration}
        />
      )}
      {step === 'critic_agent' && (
        criticReport
          ? <CriticReportDetail report={criticReport} iterationLabel={iteration} />
          : <Empty message="Aucun rapport critique pour cette itération." />
      )}
      {step === 'revision_agent' && (
        <JsonOutputView agentRun={agentRun} isRunning={isRunning} />
      )}
      {step === 'clipper_agent' && (
        <JsonOutputView agentRun={agentRun} isRunning={isRunning} />
      )}
      {step === 'short_editor_agent' && (
        <VideoView
          videos={videos?.filter((v) => v.video_type?.startsWith('short_'))}
          isRunning={isRunning}
          emptyMessage="Aucun short généré."
          projectId={projectId}
        />
      )}
    </Box>
  )
}
