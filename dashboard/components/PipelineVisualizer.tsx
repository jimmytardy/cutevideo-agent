'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import IconButton from '@mui/material/IconButton'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Alert from '@mui/material/Alert'
import Stack from '@mui/material/Stack'
import Accordion from '@mui/material/Accordion'
import AccordionSummary from '@mui/material/AccordionSummary'
import AccordionDetails from '@mui/material/AccordionDetails'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ReplayIcon from '@mui/icons-material/Replay'
import { fetcher, type AgentRun, type CriticReport, type MediaProgress, mediaProgressUrl } from '@/lib/api'
import {
  AGENT_LABELS,
  DELETION_SUMMARY,
  deriveAgentStatus,
  derivePostProdStatus,
  deriveResearchStatus,
  deriveScenarioStatus,
  effectiveMaxIterations,
  getCriticReportForIteration,
  getIterationRowState,
  isCriticLoopApproved,
  matchesSelection,
  statusDotColor,
  type AgentStatus,
  type PipelineSelection,
} from '@/lib/pipeline'

interface ConfirmTarget {
  step: string
  label: string
  iteration?: number
}

interface AgentCardProps {
  step: string
  status: AgentStatus
  selected: boolean
  disabled?: boolean
  criticScore?: number
  criticApproved?: boolean
  onSelect?: () => void
  onReplay?: () => void
  onRestartFromCritic?: () => void
  restartCriticLoading?: boolean
}

function MediaAgentProgressChip({
  projectId,
  iteration,
  status,
}: {
  projectId: string
  iteration: number
  status: AgentStatus
}) {
  const shouldFetch = status === 'running' || status === 'success'
  const { data } = useSWR<MediaProgress>(
    shouldFetch ? mediaProgressUrl(projectId, iteration) : null,
    fetcher,
    { refreshInterval: status === 'running' ? 5000 : 0 },
  )
  if (!data || data.total === 0) return null
  return (
    <Chip
      size="small"
      label={`${data.found}/${data.total} (${data.percent}%)`}
      color={data.percent >= 100 ? 'success' : status === 'running' ? 'info' : 'default'}
      sx={{ mt: 0.25, height: 18, fontSize: 10 }}
    />
  )
}

function AgentCard({
  step,
  status,
  selected,
  disabled = false,
  criticScore,
  criticApproved,
  projectId,
  iteration,
  onSelect,
  onReplay,
  onRestartFromCritic,
  restartCriticLoading,
}: AgentCardProps & { projectId?: string; iteration?: number }) {
  const dotColor = statusDotColor(status)
  const isPlanned = status === 'planned'
  const label = AGENT_LABELS[step] ?? step

  return (
    <Card
      onClick={() => !disabled && onSelect?.()}
      sx={{
        minWidth: 120,
        cursor: disabled ? 'default' : onSelect ? 'pointer' : undefined,
        opacity: isPlanned ? 0.55 : 1,
        border: selected
          ? '2px solid'
          : status === 'running'
            ? '1px solid #3b82f6'
            : status === 'stopped'
              ? '1px solid #f59e0b'
              : isPlanned
                ? '1px dashed'
                : undefined,
        borderColor: selected ? 'primary.main' : isPlanned ? 'text.disabled' : undefined,
        bgcolor: selected ? 'action.selected' : undefined,
        transition: 'box-shadow 0.15s, border-color 0.15s',
        '&:hover': !disabled && onSelect ? { boxShadow: 3 } : undefined,
      }}
    >
      <CardContent sx={{ py: 1.25, px: 1.5, '&:last-child': { pb: 1.25 } }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 0.5 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75, minWidth: 0 }}>
            <Box
              sx={{
                width: 8,
                height: 8,
                borderRadius: '50%',
                bgcolor: dotColor,
                flexShrink: 0,
                boxShadow: status === 'running' || status === 'stopped' ? `0 0 6px ${dotColor}` : undefined,
              }}
            />
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2" fontWeight={600} noWrap>
                {label}
              </Typography>
              {step === 'critic_agent' && criticScore != null && (
                <Chip
                  size="small"
                  label={`${criticScore}/100`}
                  color={criticApproved ? 'success' : criticScore >= 50 ? 'warning' : 'error'}
                  sx={{ mt: 0.25, height: 18, fontSize: 10 }}
                />
              )}
              {step === 'media_agent' && projectId != null && iteration != null && (
                <MediaAgentProgressChip
                  projectId={projectId}
                  iteration={iteration}
                  status={status}
                />
              )}
            </Box>
          </Box>
          <Box sx={{ display: 'flex', flexShrink: 0 }}>
            {onRestartFromCritic && (
              <IconButton
                size="small"
                disabled={restartCriticLoading}
                onClick={(e) => { e.stopPropagation(); onRestartFromCritic() }}
                title="Relancer depuis cette itération"
                sx={{ opacity: 0.7, '&:hover': { opacity: 1 } }}
              >
                <ReplayIcon sx={{ fontSize: 16 }} />
              </IconButton>
            )}
            {onReplay && !onRestartFromCritic && (
              <IconButton
                size="small"
                disabled={status === 'pending' || status === 'planned'}
                onClick={(e) => { e.stopPropagation(); onReplay() }}
                title={
                  status === 'running'
                    ? `Forcer la reprise depuis ${label} (agent en cours ou bloqué)`
                    : `Relancer depuis ${label}`
                }
                sx={{
                  opacity: status === 'pending' || status === 'planned' ? 0.2 : 0.6,
                  '&:hover:not(:disabled)': { opacity: 1 },
                }}
              >
                <ReplayIcon sx={{ fontSize: 16 }} />
              </IconButton>
            )}
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}

function AgentChain({
  steps,
  iteration,
  rowState,
  agentRuns,
  redisStatuses,
  projectStatus,
  projectId,
  selection,
  onSelect,
  onReplay,
  criticReports,
  onRestartFromCritic,
  restartingReportId,
}: {
  steps: string[]
  iteration: number
  rowState: ReturnType<typeof getIterationRowState>
  agentRuns: AgentRun[]
  redisStatuses: Record<string, string> | undefined
  projectStatus: string
  projectId: string
  selection: PipelineSelection | undefined
  onSelect?: (sel: PipelineSelection) => void
  onReplay?: (step: string) => void
  criticReports: CriticReport[]
  onRestartFromCritic?: (reportId: string) => void
  restartingReportId?: string | null
}) {
  const report = getCriticReportForIteration(criticReports, iteration)
  const isPlannedRow = rowState === 'planned'

  return (
    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
      {steps.map((step, idx) => {
        const status = deriveAgentStatus(
          step,
          iteration,
          rowState,
          agentRuns,
          redisStatuses,
          projectStatus,
        )
        const sel: PipelineSelection = { step, iteration }
        const isCritic = step === 'critic_agent'

        return (
          <Box key={step} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AgentCard
              step={step}
              status={status}
              selected={selection ? matchesSelection(selection, step, iteration) : false}
              disabled={isPlannedRow}
              criticScore={isCritic && report ? report.global_score ?? undefined : undefined}
              criticApproved={isCritic && report ? report.decision === 'approve' : undefined}
              projectId={projectId}
              iteration={iteration}
              onSelect={() => onSelect?.(sel)}
              onReplay={!isPlannedRow && onReplay ? () => onReplay(step) : undefined}
              onRestartFromCritic={
                isCritic && report && onRestartFromCritic
                  ? () => onRestartFromCritic(report.id)
                  : undefined
              }
              restartCriticLoading={isCritic && report && restartingReportId === report.id}
            />
            {idx < steps.length - 1 && (
              <ArrowForwardIcon sx={{ color: 'text.disabled', fontSize: 16 }} />
            )}
          </Box>
        )
      })}
    </Box>
  )
}

function iterationRowChip(rowState: ReturnType<typeof getIterationRowState>) {
  if (rowState === 'planned') return <Chip size="small" label="Prévue" variant="outlined" />
  if (rowState === 'active') return <Chip size="small" label="En cours" color="info" />
  if (rowState === 'failed') return <Chip size="small" label="Échouée" color="error" />
  return <Chip size="small" label="Terminée" color="success" variant="outlined" />
}

function IterationRow({
  iter,
  rowState,
  agentRuns,
  redisStatuses,
  projectStatus,
  projectId,
  selection,
  onSelect,
  onReplay,
  criticReports,
  onRestartFromCritic,
  restartingReportId,
}: {
  iter: number
  rowState: ReturnType<typeof getIterationRowState>
  agentRuns: AgentRun[]
  redisStatuses: Record<string, string> | undefined
  projectStatus: string
  projectId: string
  selection: PipelineSelection | undefined
  onSelect?: (sel: PipelineSelection) => void
  onReplay?: (step: string) => void
  criticReports: CriticReport[]
  onRestartFromCritic?: (reportId: string) => void
  restartingReportId?: string | null
}) {
  const steps = iter === 1
    ? ['media_agent', 'narrator_agent', 'editor_agent', 'subtitle_agent', 'critic_agent']
    : ['revision_agent', 'media_agent', 'narrator_agent', 'editor_agent', 'subtitle_agent', 'critic_agent']

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: rowState === 'active' ? '1px solid' : '1px solid transparent',
        borderColor: rowState === 'active' ? 'info.main' : 'divider',
        bgcolor: rowState === 'planned' ? 'action.hover' : undefined,
        opacity: rowState === 'planned' ? 0.85 : 1,
      }}
    >
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
        <Typography variant="body2" fontWeight={700}>
          Itération {iter}
        </Typography>
        {iterationRowChip(rowState)}
      </Box>
      <AgentChain
        steps={steps}
        iteration={iter}
        rowState={rowState}
        agentRuns={agentRuns}
        redisStatuses={redisStatuses}
        projectStatus={projectStatus}
        projectId={projectId}
        selection={selection}
        onSelect={(sel) => onSelect?.(sel)}
        onReplay={onReplay}
        criticReports={criticReports}
        onRestartFromCritic={onRestartFromCritic}
        restartingReportId={restartingReportId}
      />
    </Box>
  )
}

interface Props {
  projectId: string
  isShort?: boolean
  maxIterations: number
  projectStatus: string
  agentRuns: AgentRun[]
  criticReports: CriticReport[]
  onRunFrom?: (step: string) => void
  onRestartFromCritic?: (reportId: string) => void
  selection?: PipelineSelection
  onSelect?: (sel: PipelineSelection | null) => void
  restartingReportId?: string | null
}

export default function PipelineVisualizer({
  projectId,
  isShort = false,
  maxIterations,
  projectStatus,
  agentRuns,
  criticReports,
  onRunFrom,
  onRestartFromCritic,
  selection,
  onSelect,
  restartingReportId,
}: Props) {
  const [confirmTarget, setConfirmTarget] = useState<ConfirmTarget | null>(null)

  const { data: redisStatuses } = useSWR<Record<string, string>>(
    `/api/v1/agents/status/${projectId}`,
    fetcher,
    { refreshInterval: projectStatus === 'running' ? 2000 : 0 },
  )

  const effectiveMax = effectiveMaxIterations(maxIterations, isShort)
  const criticApproved = isCriticLoopApproved(criticReports)
  const includeClipper = !isShort

  const researchStatus = deriveResearchStatus(agentRuns, redisStatuses, projectStatus)
  const scenarioStatus = deriveScenarioStatus(agentRuns, redisStatuses, projectStatus)

  const handleConfirm = () => {
    if (confirmTarget && onRunFrom) onRunFrom(confirmTarget.step)
    setConfirmTarget(null)
  }

  const iterationRows = Array.from({ length: effectiveMax }, (_, i) => {
    const iter = i + 1
    return {
      iter,
      rowState: getIterationRowState(iter, criticReports, projectStatus, agentRuns),
    }
  })
  const startedRows = iterationRows.filter((r) => r.rowState !== 'planned')
  const plannedRows = iterationRows.filter((r) => r.rowState === 'planned')
  const selectionInPlanned = selection?.iteration != null
    && plannedRows.some((r) => r.iter === selection.iteration)

  const renderIterationRow = (iter: number, rowState: ReturnType<typeof getIterationRowState>) => (
    <IterationRow
      key={iter}
      iter={iter}
      rowState={rowState}
      agentRuns={agentRuns}
      redisStatuses={redisStatuses}
      projectStatus={projectStatus}
      projectId={projectId}
      selection={selection}
      onSelect={onSelect}
      onReplay={(step) =>
        setConfirmTarget({ step, label: AGENT_LABELS[step] ?? step, iteration: iter })
      }
      criticReports={criticReports}
      onRestartFromCritic={onRestartFromCritic}
      restartingReportId={restartingReportId}
    />
  )

  return (
    <>
      <Stack spacing={2.5}>
        {/* Préparation */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Préparation
          </Typography>
          <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
            <AgentCard
              step="research_agent"
              status={researchStatus}
              selected={selection ? matchesSelection(selection, 'research_agent') : false}
              onSelect={() => onSelect?.({ step: 'research_agent' })}
              onReplay={
                onRunFrom && researchStatus !== 'pending' && researchStatus !== 'planned'
                  ? () => setConfirmTarget({ step: 'research_agent', label: AGENT_LABELS.research_agent })
                  : undefined
              }
            />
            <ArrowForwardIcon fontSize="small" color="disabled" />
            <AgentCard
              step="scenario_agent"
              status={scenarioStatus}
              selected={selection ? matchesSelection(selection, 'scenario_agent') : false}
              onSelect={() => onSelect?.({ step: 'scenario_agent' })}
              onReplay={
                onRunFrom && scenarioStatus !== 'pending' && scenarioStatus !== 'planned'
                  ? () => setConfirmTarget({ step: 'scenario_agent', label: AGENT_LABELS.scenario_agent })
                  : undefined
              }
            />
          </Box>
        </Box>

        {/* Boucle critique */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Boucle critique (max {effectiveMax} itérations)
          </Typography>
          <Stack spacing={1.5}>
            {startedRows.map(({ iter, rowState }) => renderIterationRow(iter, rowState))}

            {plannedRows.length > 0 && (
              <Accordion
                defaultExpanded={selectionInPlanned}
                disableGutters
                elevation={0}
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: '8px !important',
                  '&:before': { display: 'none' },
                }}
              >
                <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                  <Typography variant="body2" fontWeight={700}>
                    Itérations en attente
                  </Typography>
                  <Chip
                    size="small"
                    label={plannedRows.length}
                    variant="outlined"
                    sx={{ ml: 1 }}
                  />
                </AccordionSummary>
                <AccordionDetails sx={{ pt: 0 }}>
                  <Stack spacing={1.5}>
                    {plannedRows.map(({ iter, rowState }) => renderIterationRow(iter, rowState))}
                  </Stack>
                </AccordionDetails>
              </Accordion>
            )}
          </Stack>
        </Box>

        {/* Post-production */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Post-production
            {!criticApproved && projectStatus !== 'running' && (
              <Typography component="span" variant="caption" sx={{ ml: 1 }}>
                — après approbation critique
              </Typography>
            )}
          </Typography>
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
            {includeClipper && (
              <>
                <AgentCard
                  step="clipper_agent"
                  status={derivePostProdStatus(
                    'clipper_agent',
                    agentRuns,
                    redisStatuses,
                    projectStatus,
                    criticApproved,
                  )}
                  selected={selection ? matchesSelection(selection, 'clipper_agent') : false}
                  disabled={!criticApproved && projectStatus !== 'running'}
                  onSelect={() => onSelect?.({ step: 'clipper_agent' })}
                  onReplay={
                    onRunFrom && criticApproved
                      ? () => setConfirmTarget({ step: 'clipper_agent', label: AGENT_LABELS.clipper_agent })
                      : undefined
                  }
                />
                <ArrowForwardIcon sx={{ color: 'text.disabled', fontSize: 16 }} />
              </>
            )}
            <AgentCard
              step="short_editor_agent"
              status={derivePostProdStatus(
                'short_editor_agent',
                agentRuns,
                redisStatuses,
                projectStatus,
                criticApproved,
              )}
              selected={selection ? matchesSelection(selection, 'short_editor_agent') : false}
              disabled={!criticApproved && projectStatus !== 'running'}
              onSelect={() => onSelect?.({ step: 'short_editor_agent' })}
              onReplay={
                onRunFrom && criticApproved
                  ? () => setConfirmTarget({ step: 'short_editor_agent', label: AGENT_LABELS.short_editor_agent })
                  : undefined
              }
            />
          </Box>
        </Box>
      </Stack>

      <Dialog open={!!confirmTarget} onClose={() => setConfirmTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>
          Relancer depuis « {confirmTarget?.label} » ?
          {confirmTarget?.iteration != null && ` (itération ${confirmTarget.iteration})`}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            Les données suivantes seront supprimées et recréées :
          </Typography>
          <List dense disablePadding>
            {(DELETION_SUMMARY[confirmTarget?.step ?? ''] ?? []).map((item) => (
              <ListItem key={item} disableGutters sx={{ py: 0.25 }}>
                <ListItemText primary={`• ${item}`} primaryTypographyProps={{ variant: 'body2' }} />
              </ListItem>
            ))}
          </List>
          {confirmTarget?.step === 'subtitle_agent' && (
            <Alert severity="info" sx={{ mt: 1.5 }} icon={false}>
              Les sous-titres étant intégrés à la vidéo, le montage sera entièrement refait.
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmTarget(null)}>Annuler</Button>
          <Button variant="contained" color="warning" onClick={handleConfirm}>
            Confirmer le relancement
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
