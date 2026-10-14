'use client'

import { useMemo, useState } from 'react'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Paper from '@mui/material/Paper'
import Stack from '@mui/material/Stack'
import Typography from '@mui/material/Typography'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  STUDIO_STEPS,
  studioStepLabel,
  type AgentRun,
  type CriticReport,
  type StudioCritiqueFeedback,
  type StudioRequestedChange,
} from '@/lib/api'
import { runStatusColor, runStatusLabel } from '@/lib/status'



interface Props {
  agentRuns: AgentRun[]
  criticReports: CriticReport[]
}

interface Selection {
  iteration: number
  agent: string
}

/** Pipeline Claude Studio : 5 rôles par itération, résultat de chaque sous-agent au clic. */
export default function StudioPipeline({ agentRuns, criticReports }: Props) {
  const [selection, setSelection] = useState<Selection | null>(null)

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
  const selectedRun = selection ? byIteration.get(selection.iteration)?.get(selection.agent) : undefined
  const selectedReport =
    selection?.agent === 'critic_agent'
      ? criticReports.find((r) => r.iteration === selection.iteration)
      : undefined

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
              const status = run?.status ?? ''
              const report = agent === 'critic_agent' ? criticReports.find((r) => r.iteration === iteration) : undefined
              const isSelected = selection?.iteration === iteration && selection.agent === agent
              return (
                <Chip
                  key={agent}
                  clickable={!!run}
                  onClick={run ? () => setSelection(isSelected ? null : { iteration, agent }) : undefined}
                  variant={isSelected ? 'filled' : 'outlined'}
                  color={runStatusColor(status)}
                  label={
                    report?.global_score != null
                      ? `${studioStepLabel(agent)} · ${report.global_score}/100`
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
          {selectedReport && <CritiqueDetail report={selectedReport} />}
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
          Cliquez sur une étape pour voir le compte rendu du sous-agent.
        </Typography>
      )}
    </Stack>
  )
}

function CritiqueDetail({ report }: { report: CriticReport }) {
  const feedback = (report.feedback ?? {}) as StudioCritiqueFeedback
  const changes = (report.requested_changes ?? []) as unknown as StudioRequestedChange[]
  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="body2" sx={{ mb: 1 }}>
        Score <strong>{report.global_score ?? '—'}/100</strong> · décision{' '}
        <strong>{report.decision === 'approve' ? 'approuvée' : 'itérer'}</strong>
      </Typography>
      {feedback.summary && (
        <Typography variant="body2" sx={{ mb: 1 }}>
          {feedback.summary}
        </Typography>
      )}
      <FeedbackList title="Points forts" items={feedback.strengths} />
      <FeedbackList title="Problèmes" items={feedback.issues} />
      {changes.length > 0 && (
        <FeedbackList
          title="Corrections demandées"
          items={changes.map((c) => `${studioRoleLabel(c.role)} : ${c.instruction}`)}
        />
      )}
    </Box>
  )
}

function FeedbackList({ title, items }: { title: string; items?: string[] }) {
  if (!items?.length) return null
  return (
    <Box sx={{ mb: 1 }}>
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
