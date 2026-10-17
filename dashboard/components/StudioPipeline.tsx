'use client'

import { useMemo, useState, type ReactNode } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import LinearProgress from '@mui/material/LinearProgress'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import { useMediaToken } from '@/lib/useMediaToken'
import {
  STUDIO_STEPS,
  fetcher,
  studioFileUrl,
  studioStepLabel,
  type AgentRun,
  type CriticReport,
  type Scenario,
  type StudioArtifacts,
  type StudioCritiqueFile,
  type StudioMediaFile,
  type StudioRequestedChange,
  type StudioScenarioCritiqueFile,
  type StudioScenarioFile,
} from '@/lib/api'
import { runStatusColor, runStatusLabel } from '@/lib/status'
import { useAgentLogSse } from '@/lib/useAgentLogSse'
import AgentLiveLog from '@/components/AgentLiveLog'

interface Props {
  projectId: string
  agentRuns: AgentRun[]
  criticReports: CriticReport[]
  /** Scénario persisté en base : repli quand le run dir a été purgé. */
  scenario?: Scenario | null
  /** Passes de la boucle scénario persistées (Project.config.claude_studio) : repli quand le run dir a été purgé. */
  scenarioCritiques?: StudioScenarioCritiqueFile[]
  refreshInterval?: number
}

interface Selection {
  iteration: number
  agent: string
}

/** Grille virale de la critique (studio/workspace/.claude/agents/critique.md) : libellé et note maximale. */
const CRITERIA: Array<{ key: string; label: string; max: number }> = [
  { key: 'hook', label: 'Hook', max: 20 },
  { key: 'retention', label: 'Rétention', max: 15 },
  { key: 'valeur', label: 'Valeur', max: 15 },
  { key: 'visuels', label: 'Visuels', max: 20 },
  { key: 'voix_son', label: 'Voix & son', max: 15 },
  { key: 'sous_titres', label: 'Sous-titres', max: 5 },
  { key: 'chute_partage', label: 'Chute & partage', max: 10 },
]

/** Grille de l'analyse scénario (studio/workspace/.claude/agents/critique-scenario.md). */
const SCENARIO_CRITERIA: Array<{ key: string; label: string; max: number }> = [
  { key: 'hook', label: 'Hook', max: 20 },
  { key: 'structure', label: 'Structure & relances', max: 15 },
  { key: 'valeur_verite', label: 'Valeur & véracité', max: 20 },
  { key: 'oralite', label: 'Oralité & clarté', max: 15 },
  { key: 'duree', label: 'Durée', max: 10 },
  { key: 'chute_boucle', label: 'Chute & boucle', max: 15 },
  { key: 'brief', label: 'Brief créatif', max: 5 },
]

/** Pipeline Claude Studio : 5 rôles par itération, résultat et fichier produit de chaque sous-agent au clic. */
export default function StudioPipeline({
  projectId,
  agentRuns,
  criticReports,
  scenario,
  scenarioCritiques,
  refreshInterval = 0,
}: Props) {
  const [selection, setSelection] = useState<Selection | null>(null)
  const { data: artifacts } = useSWR<StudioArtifacts>(
    `/api/v1/projects/${projectId}/studio/artifacts`,
    fetcher,
    { refreshInterval },
  )

  const byIteration = useMemo(() => {
    const map = new Map<number, Map<string, AgentRun>>()
    const sorted = [...agentRuns].sort((a, b) => (a.started_at ?? '').localeCompare(b.started_at ?? ''))
    for (const run of sorted) {
      if (!run.agent_name || !STUDIO_STEPS.includes(run.agent_name)) continue
      const steps = map.get(run.iteration) ?? new Map<string, AgentRun>()
      steps.set(run.agent_name, run)
      map.set(run.iteration, steps)
    }
    return map
  }, [agentRuns])

  const iterations = byIteration.size > 0 ? [...byIteration.keys()].sort((a, b) => a - b) : [1]
  const lastIteration = iterations[iterations.length - 1]
  const selectedRun = selection ? byIteration.get(selection.iteration)?.get(selection.agent) : undefined

  const critiqueScore = (iteration: number): number | null | undefined =>
    artifacts?.iterations[String(iteration)]?.critique?.score ??
    criticReports.find((r) => r.iteration === iteration)?.global_score

  const scenarioPasses = artifacts?.available ? artifacts.scenario_critiques ?? [] : scenarioCritiques ?? []
  const stepScore = (agent: string, iteration: number): number | null | undefined => {
    if (agent === 'critic_agent') return critiqueScore(iteration)
    // La boucle scénario tourne pendant l'itération 1 : note de la dernière passe.
    if (agent === 'scenario_critic_agent' && iteration === 1) return scenarioPasses[scenarioPasses.length - 1]?.score
    return null
  }

  return (
    <Stack spacing={2}>
      {iterations.map((iteration) => (
        <Box key={iteration}>
          <Typography variant="overline" color="text.secondary">
            Itération {iteration}
          </Typography>
          <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', gap: 1, mt: 0.5 }}>
            {STUDIO_STEPS.map((agent) => {
              const run = byIteration.get(iteration)?.get(agent)
              // La miniature n'est produite qu'après la boucle : pas de puce vide dans les itérations précédentes.
              if (agent === 'thumbnail_agent' && !run && iteration !== lastIteration) return null
              const status = run?.status ?? ''
              const score = stepScore(agent, iteration)
              const isSelected = selection?.iteration === iteration && selection.agent === agent
              return (
                <Chip
                  key={agent}
                  clickable={!!run}
                  onClick={run ? () => setSelection(isSelected ? null : { iteration, agent }) : undefined}
                  variant={isSelected ? 'filled' : 'outlined'}
                  color={runStatusColor(status)}
                  label={
                    score != null
                      ? `${studioStepLabel(agent)} · ${score}/100`
                      : `${studioStepLabel(agent)}${status ? ` · ${runStatusLabel(status)}` : ''}`
                  }
                />
              )
            })}
          </Stack>
        </Box>
      ))}

      {selectedRun ? (
        <Paper variant="outlined" sx={{ p: 2 }}>
          <Typography variant="subtitle2" sx={{ mb: 1 }}>
            {studioStepLabel(selectedRun.agent_name ?? '')} — itération {selectedRun.iteration}
            {selectedRun.input_json?.description ? ` · ${String(selectedRun.input_json.description)}` : ''}
          </Typography>
          {selectedRun.error ? (
            <Typography variant="body2" color="error" sx={{ whiteSpace: 'pre-wrap' }}>
              {selectedRun.error}
            </Typography>
          ) : (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {String(selectedRun.output_json?.summary ?? 'En cours…')}
            </Typography>
          )}

          <StepTerminal key={selectedRun.id} projectId={projectId} run={selectedRun} />

          <StepOutput
            projectId={projectId}
            agent={selectedRun.agent_name ?? ''}
            iteration={selectedRun.iteration}
            isLastIteration={selectedRun.iteration === lastIteration}
            artifacts={artifacts}
            dbScenario={scenario}
            scenarioPasses={scenarioPasses}
            dbReport={criticReports.find((r) => r.iteration === selectedRun.iteration)}
          />

          {selectedRun.input_json?.prompt ? (
            <Accordion disableGutters sx={{ mt: 2 }}>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="caption">Consignes reçues du producteur</Typography>
              </AccordionSummary>
              <AccordionDetails>
                <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap', fontSize: 12 }}>
                  {String(selectedRun.input_json.prompt)}
                </Typography>
              </AccordionDetails>
            </Accordion>
          ) : null}
        </Paper>
      ) : (
        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
          Cliquez sur une étape pour voir le compte rendu et le fichier produit par le sous-agent.
        </Typography>
      )}
    </Stack>
  )
}

/** Trace d'exécution du sous-agent : ouverte et en direct pendant le run, repliée (« Afficher la trace ») ensuite. */
function StepTerminal({ projectId, run }: { projectId: string; run: AgentRun }) {
  const runIsActive = run.status === 'running'
  const [open, setOpen] = useState(runIsActive)
  const { lines, running, connected } = useAgentLogSse(projectId, run.id, open || runIsActive)
  return (
    <AgentLiveLog
      title={`Terminal ${studioStepLabel(run.agent_name ?? '')}`}
      lines={lines}
      running={running || (runIsActive && !connected)}
      loaded={connected}
      open={open}
      onOpenChange={setOpen}
    />
  )
}

interface StepOutputProps {
  projectId: string
  agent: string
  iteration: number
  isLastIteration: boolean
  artifacts?: StudioArtifacts
  dbScenario?: Scenario | null
  scenarioPasses: StudioScenarioCritiqueFile[]
  dbReport?: CriticReport
}

/** Fichier produit par le rôle : scénario lisible, voix, rendu, miniatures ou critique notée. */
function StepOutput({
  projectId,
  agent,
  iteration,
  isLastIteration,
  artifacts,
  dbScenario,
  scenarioPasses,
  dbReport,
}: StepOutputProps) {
  const mediaToken = useMediaToken()
  const slot = artifacts?.iterations[String(iteration)]
  const purged = artifacts && !artifacts.available
  // scenario.json et voice.wav sont réécrits à chaque passage : seule la dernière version existe.
  const overwritten = !isLastIteration ? 'Version la plus récente (le fichier est réécrit à chaque itération).' : null

  switch (agent) {
    case 'scenario_agent': {
      const fromDb: StudioScenarioFile | null = dbScenario?.segments?.length
        ? { beats: dbScenario.segments }
        : null
      const file = artifacts?.scenario ?? fromDb
      return (
        <OutputBlock title="scenario.json" note={artifacts?.scenario ? overwritten : null}>
          {file ? <ScenarioView scenario={file} /> : <Missing purged={purged} />}
        </OutputBlock>
      )
    }
    case 'scenario_critic_agent':
      return (
        <OutputBlock title="scenario_critique_*.json">
          {scenarioPasses.length ? (
            <Stack spacing={2} divider={<Divider flexItem />}>
              {scenarioPasses.map((pass) => (
                <Box key={pass.iteration}>
                  <Typography variant="overline" color="text.secondary">
                    Passe {pass.iteration}
                  </Typography>
                  <CritiqueDetail critique={scenarioCritiqueView(pass)} criteria={SCENARIO_CRITERIA} />
                  <FeedbackList title="Faits à vérifier sur le web" items={pass.unverified_claims} />
                </Box>
              ))}
            </Stack>
          ) : (
            <Missing purged={purged} />
          )}
        </OutputBlock>
      )
    case 'narrator_agent': {
      const voice = artifacts?.voice
      return (
        <OutputBlock title="voice.wav" note={voice ? overwritten : null}>
          {voice ? (
            <>
              <Box component="audio" controls preload="metadata" src={mediaToken ? studioFileUrl(projectId, voice, mediaToken) : undefined} sx={{ width: '100%', maxWidth: 480 }} />
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                {[
                  voice.duration_s != null && `${voice.duration_s.toFixed(1)} s`,
                  voice.engine && `moteur ${voice.engine}`,
                  voice.voice && `voix ${voice.voice}`,
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </Typography>
            </>
          ) : (
            <Missing purged={purged} />
          )}
        </OutputBlock>
      )
    }
    case 'editor_agent':
      return (
        <OutputBlock title={`renders/v${iteration}.mp4`}>
          {slot?.render ? (
            <Box
              component="video"
              controls
              preload="metadata"
              src={mediaToken ? studioFileUrl(projectId, slot.render, mediaToken) : undefined}
              sx={{ width: '100%', maxWidth: 300, aspectRatio: '9 / 16', bgcolor: 'black', borderRadius: 1 }}
            />
          ) : (
            <Missing purged={purged} />
          )}
        </OutputBlock>
      )
    case 'thumbnail_agent':
      return (
        <OutputBlock title="Miniatures">
          {slot?.thumbnails.length ? (
            <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 2 }}>
              {slot.thumbnails.map((thumb) => (
                <ThumbnailImage key={thumb.path} projectId={projectId} file={thumb} />
              ))}
            </Stack>
          ) : (
            <Missing purged={purged} />
          )}
          {isLastIteration && artifacts?.thumbnail?.text && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
              Texte : {artifacts.thumbnail.text}
            </Typography>
          )}
        </OutputBlock>
      )
    case 'critic_agent': {
      const critique = slot?.critique ?? (dbReport ? critiqueFromReport(dbReport) : null)
      return (
        <OutputBlock title={`critique_${iteration}.json`}>
          {critique ? <CritiqueDetail critique={critique} /> : <Missing purged={purged} />}
        </OutputBlock>
      )
    }
    default:
      return null
  }
}

function OutputBlock({ title, note, children }: { title: string; note?: string | null; children: ReactNode }) {
  return (
    <Box sx={{ mt: 2 }}>
      <Divider sx={{ mb: 1.5 }} />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1, fontFamily: 'monospace' }}>
        {title}
        {note ? ` — ${note}` : ''}
      </Typography>
      {children}
    </Box>
  )
}

function Missing({ purged }: { purged?: boolean }) {
  return (
    <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>
      {purged ? 'Fichiers de travail supprimés (purge du run).' : 'Pas encore de fichier produit.'}
    </Typography>
  )
}

function ScenarioView({ scenario }: { scenario: StudioScenarioFile }) {
  const tags = [
    scenario.visual_mode && `Visuel : ${scenario.visual_mode}`,
    scenario.theme && `Thème : ${scenario.theme}`,
    scenario.mood && `Ton : ${scenario.mood}`,
    scenario.music_mood && `Musique : ${scenario.music_mood}`,
  ].filter(Boolean) as string[]
  const beats = scenario.beats ?? []
  const words = beats.reduce((n, b) => n + (b.text?.trim().split(/\s+/).filter(Boolean).length ?? 0), 0)

  return (
    <Stack spacing={2}>
      {(scenario.title || tags.length > 0 || scenario.accent) && (
        <Box>
          {scenario.title && <Typography variant="h6">{scenario.title}</Typography>}
          <Stack direction="row" sx={{ flexWrap: 'wrap', gap: 1, mt: 0.5 }}>
            {tags.map((tag) => (
              <Chip key={tag} label={tag} size="small" variant="outlined" />
            ))}
            {scenario.accent && (
              <Chip
                size="small"
                variant="outlined"
                label={`Accent ${scenario.accent}`}
                icon={<Box sx={{ width: 12, height: 12, borderRadius: '50%', bgcolor: scenario.accent, ml: 1 }} />}
              />
            )}
            {words > 0 && <Chip size="small" variant="outlined" label={`${words} mots · ~${Math.round(words / 3.1)} s`} />}
          </Stack>
        </Box>
      )}

      {scenario.hook && (
        <Box sx={{ borderLeft: 3, borderColor: 'primary.main', pl: 1.5 }}>
          <Typography variant="caption" color="text.secondary">
            Hook
          </Typography>
          <Typography variant="body1" sx={{ fontWeight: 600 }}>
            {scenario.hook}
          </Typography>
        </Box>
      )}

      {beats.length > 0 && (
        <Box component="ol" sx={{ m: 0, pl: 3 }}>
          {beats.map((beat, i) => (
            <Box component="li" key={i} sx={{ mb: 1.5 }}>
              <Typography variant="body2">
                {beat.text}
                {beat.on_screen_text && <Chip label={beat.on_screen_text} size="small" color="primary" sx={{ ml: 1 }} />}
              </Typography>
              {beat.visual_intent && (
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                  À l&apos;écran : {beat.visual_intent}
                </Typography>
              )}
            </Box>
          ))}
        </Box>
      )}

      {scenario.cta && (
        <Typography variant="body2">
          <strong>CTA :</strong> {scenario.cta}
        </Typography>
      )}

      {scenario.publish && (scenario.publish.title || scenario.publish.description) && (
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="caption" color="text.secondary">
            Publication
          </Typography>
          {scenario.publish.title && <Typography variant="subtitle2">{scenario.publish.title}</Typography>}
          {scenario.publish.description && (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
              {scenario.publish.description}
            </Typography>
          )}
          {scenario.publish.hashtags?.length ? (
            <Typography variant="body2" color="primary" sx={{ mt: 0.5 }}>
              {scenario.publish.hashtags.join(' ')}
            </Typography>
          ) : null}
        </Paper>
      )}
    </Stack>
  )
}

function ThumbnailImage({ projectId, file }: { projectId: string; file: StudioMediaFile }) {
  const name = file.path.split('/').pop() ?? file.path
  const mediaToken = useMediaToken()
  const src = mediaToken ? studioFileUrl(projectId, file, mediaToken) : undefined
  return (
    <Box sx={{ maxWidth: name.includes('16x9') ? 360 : 220 }}>
      <Box component="a" href={src} target="_blank" rel="noopener">
        <Box
          component="img"
          src={src}
          alt={name}
          sx={{ width: '100%', maxHeight: 400, objectFit: 'contain', borderRadius: 1, border: 1, borderColor: 'divider' }}
        />
      </Box>
      <Typography variant="caption" color="text.secondary" sx={{ fontFamily: 'monospace' }}>
        {name}
      </Typography>
    </Box>
  )
}

function critiqueFromReport(report: CriticReport): StudioCritiqueFile {
  const feedback = (report.feedback ?? {}) as StudioCritiqueFile
  return {
    ...feedback,
    score: report.global_score ?? undefined,
    decision: report.decision ?? undefined,
    changes: (report.requested_changes ?? []) as unknown as StudioRequestedChange[],
  }
}

function scenarioCritiqueView(pass: StudioScenarioCritiqueFile): StudioCritiqueFile {
  return {
    ...pass,
    changes: (pass.changes ?? []).map((instruction) => ({ role: 'scenariste', instruction })),
  }
}

function CritiqueDetail({
  critique,
  criteria: grid = CRITERIA,
}: {
  critique: StudioCritiqueFile
  criteria?: Array<{ key: string; label: string; max: number }>
}) {
  const scores = critique.scores ?? {}
  const criteria = [
    ...grid.filter((c) => typeof scores[c.key] === 'number'),
    ...Object.keys(scores)
      .filter((key) => typeof scores[key] === 'number' && !grid.some((c) => c.key === key))
      .map((key) => ({ key, label: key, max: 0 })),
  ]
  const approved = critique.decision === 'approve'
  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={2} sx={{ alignItems: 'baseline', flexWrap: 'wrap' }}>
        <Typography variant="h4" component="span" sx={{ fontWeight: 700 }}>
          {critique.score ?? '—'}
          <Typography component="span" variant="body2" color="text.secondary">
            /100
          </Typography>
        </Typography>
        {critique.decision && (
          <Chip size="small" color={approved ? 'success' : 'warning'} label={approved ? 'Approuvée' : 'Nouvelle itération'} />
        )}
        {critique.analysis?.source && (
          <Typography variant="caption" color="text.secondary">
            analyse : {critique.analysis.source}
          </Typography>
        )}
      </Stack>

      {criteria.length > 0 && (
        <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' }, columnGap: 3, rowGap: 1 }}>
          {criteria.map(({ key, label, max }) => {
            const value = scores[key]
            const ratio = max > 0 ? Math.min(1, value / max) : 0
            return (
              <Box key={key}>
                <Stack direction="row" sx={{ justifyContent: 'space-between' }}>
                  <Typography variant="body2">{label}</Typography>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {value}
                    {max > 0 ? `/${max}` : ''}
                  </Typography>
                </Stack>
                {max > 0 && (
                  <LinearProgress
                    variant="determinate"
                    value={ratio * 100}
                    color={ratio >= 0.75 ? 'success' : ratio >= 0.5 ? 'warning' : 'error'}
                    sx={{ height: 6, borderRadius: 3 }}
                  />
                )}
              </Box>
            )
          })}
        </Box>
      )}

      {critique.summary && <Typography variant="body2">{critique.summary}</Typography>}
      <FeedbackList title="Points forts" items={critique.strengths} />
      <FeedbackList title="Problèmes" items={critique.issues} />
      {critique.changes?.length ? (
        <FeedbackList
          title="Corrections demandées"
          items={critique.changes.map(
            (c) => `${studioRoleLabel(c.role)}${c.lines?.length ? ` (lignes ${c.lines.join(', ')})` : ''} : ${c.instruction}`,
          )}
        />
      ) : null}
      <FeedbackList title="Alertes de l'analyse" items={critique.analysis?.flags} />
    </Stack>
  )
}

function FeedbackList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null
  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {title}
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
        {items.map((item, i) => (
          <Typography component="li" variant="body2" key={i}>
            {item}
          </Typography>
        ))}
      </Box>
    </Box>
  )
}

function studioRoleLabel(role: string): string {
  const roles: Record<string, string> = {
    scenariste: 'Scénariste',
    voix: 'Voix',
    monteur: 'Monteur',
    miniaturiste: 'Miniaturiste',
  }
  return roles[role] ?? role
}
