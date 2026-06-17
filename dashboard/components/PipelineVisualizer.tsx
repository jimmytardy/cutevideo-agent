'use client'

import { useState, type MouseEvent, type ReactNode } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import IconButton from '@mui/material/IconButton'
import Tooltip from '@mui/material/Tooltip'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import CircularProgress from '@mui/material/CircularProgress'
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
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import ReplayIcon from '@mui/icons-material/Replay'
import StopIcon from '@mui/icons-material/Stop'
import { fetcher, pipelineProgressUrl, type AgentProgressItem, type AgentRun, type CriticReport, type PipelineProgressResponse } from '@/lib/api'
import {
  AGENT_LABELS,
  DELETION_SUMMARY,
  deriveAgentStatus,
  deriveHookOptimizerStatus,
  derivePostProdStatus,
  deriveResearchStatus,
  deriveOutlineStatus,
  deriveScenarioStatus,
  effectiveMaxIterations,
  getCriticReportForIteration,
  getEffectiveProjectStatus,
  getIterationRowState,
  getResumeStep,
  isCriticLoopApproved,
  isPipelineInFlight,
  isResumeTarget,
  matchesSelection,
  pickAgentProgress,
  statusDotColor,
  type AgentStatus,
  type PipelineKickoff,
  type PipelineSelection,
  type ResumeTarget,
} from '@/lib/pipeline'

interface ConfirmTarget {
  step: string
  label: string
  iteration?: number
  mode: 'resume' | 'replay'
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
  onLaunch?: () => void
  onStop?: () => void
  showLaunch?: boolean
  showStop?: boolean
  actionLoading?: boolean
  onRestartFromCritic?: () => void
  progress?: AgentProgressItem
}

function AgentProgressChip({
  progress,
  status,
}: {
  progress: AgentProgressItem
  status: AgentStatus
}) {
  const label = progress.detail
    ? `${progress.detail} (${progress.percent}%)`
    : `${progress.done}/${progress.total} (${progress.percent}%)`
  return (
    <Chip
      size="small"
      label={label}
      color={progress.percent >= 100 ? 'success' : status === 'running' ? 'info' : 'default'}
      sx={{ height: 18, fontSize: '0.65rem', '& .MuiChip-label': { px: 0.75 } }}
    />
  )
}

const AGENT_CARD_MIN_HEIGHT = 76

function AgentCardActionButton({
  title,
  onClick,
  disabled,
  color,
  variant = 'default',
  children,
}: {
  title: string
  onClick: (e: MouseEvent) => void
  disabled?: boolean
  color?: 'error' | 'primary' | 'default'
  variant?: 'default' | 'filled'
  children: ReactNode
}) {
  return (
    <Tooltip title={title} arrow placement="top">
      <span>
        <IconButton
          size="small"
          color={color === 'default' ? 'default' : color}
          disabled={disabled}
          onClick={onClick}
          sx={{
            width: 26,
            height: 26,
            p: 0.5,
            ...(variant === 'filled' && color === 'primary'
              ? {
                  bgcolor: 'primary.main',
                  color: 'primary.contrastText',
                  '&:hover': { bgcolor: 'primary.dark' },
                }
              : {
                  border: '1px solid',
                  borderColor: 'divider',
                  bgcolor: 'background.paper',
                }),
          }}
        >
          {children}
        </IconButton>
      </span>
    </Tooltip>
  )
}

function AgentCard({
  step,
  status,
  selected,
  disabled = false,
  criticScore,
  criticApproved,
  progress,
  onSelect,
  onReplay,
  onLaunch,
  onStop,
  showLaunch = false,
  showStop = false,
  actionLoading = false,
  onRestartFromCritic,
}: AgentCardProps) {
  const dotColor = statusDotColor(status)
  const isPlanned = status === 'planned'
  const label = AGENT_LABELS[step] ?? step
  const showReplay =
    onReplay && !onRestartFromCritic && !showLaunch && status !== 'pending' && status !== 'planned'
  const showCriticChip = step === 'critic_agent' && criticScore != null
  const showProgressChip = Boolean(
    progress
    && progress.total > 0
    && status !== 'pending'
    && status !== 'planned'
    && !(step === 'critic_agent' && criticScore != null),
  )
  const hasActions =
    (showStop && onStop && status === 'running')
    || (showLaunch && onLaunch)
    || !!onRestartFromCritic
    || showReplay
  const hasFooter = showCriticChip || showProgressChip

  const stopClick = (e: MouseEvent) => {
    e.stopPropagation()
    onStop?.()
  }
  const launchClick = (e: MouseEvent) => {
    e.stopPropagation()
    onLaunch?.()
  }
  const replayClick = (e: MouseEvent) => {
    e.stopPropagation()
    if (onRestartFromCritic) onRestartFromCritic()
    else onReplay?.()
  }

  return (
    <Card
      variant="outlined"
      onClick={() => !disabled && onSelect?.()}
      sx={{
        width: 'max-content',
        minWidth: 132,
        minHeight: AGENT_CARD_MIN_HEIGHT,
        boxSizing: 'border-box',
        display: 'flex',
        flexDirection: 'column',
        borderRadius: 1.5,
        borderLeftWidth: 3,
        borderLeftColor: dotColor,
        cursor: disabled ? 'default' : onSelect ? 'pointer' : undefined,
        opacity: isPlanned ? 0.55 : 1,
        borderColor: selected || showLaunch
          ? 'primary.main'
          : status === 'running'
            ? '#93c5fd'
            : status === 'stopped'
              ? '#fcd34d'
              : 'divider',
        borderWidth: selected || showLaunch ? 2 : 1,
        ...(isPlanned && !selected && !showLaunch ? { borderStyle: 'dashed' } : {}),
        bgcolor: selected
          ? 'action.selected'
          : showLaunch
            ? 'primary.50'
            : 'background.paper',
        transition: 'box-shadow 0.15s, border-color 0.15s, background-color 0.15s',
        boxShadow: selected ? 2 : showLaunch ? 1 : 0,
        '&:hover': !disabled && onSelect ? { boxShadow: 2 } : undefined,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          gap: 0.75,
          px: 1.25,
          pt: 1,
          pb: hasFooter ? 0.5 : 1,
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        <Tooltip title={status} arrow placement="top">
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
        </Tooltip>

        <Typography
          variant="body2"
          fontWeight={600}
          sx={{
            flex: 1,
            lineHeight: 1.25,
            fontSize: '0.8125rem',
            whiteSpace: 'nowrap',
            color: disabled ? 'text.disabled' : 'text.primary',
            pr: hasActions ? 0.5 : 0,
          }}
        >
          {label}
        </Typography>

        {hasActions && (
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 0.375,
              flexShrink: 0,
              ml: 0.25,
            }}
          >
            {showStop && onStop && status === 'running' && (
              <AgentCardActionButton
                title="Arrêter le pipeline"
                color="error"
                disabled={actionLoading}
                onClick={stopClick}
              >
                <StopIcon sx={{ fontSize: 15 }} />
              </AgentCardActionButton>
            )}
            {showLaunch && onLaunch && (
              <AgentCardActionButton
                title="Lancer"
                color="primary"
                variant="filled"
                disabled={actionLoading}
                onClick={launchClick}
              >
                {actionLoading
                  ? <CircularProgress size={12} color="inherit" />
                  : <PlayArrowIcon sx={{ fontSize: 15 }} />}
              </AgentCardActionButton>
            )}
            {onRestartFromCritic && (
              <AgentCardActionButton
                title="Relancer depuis cette itération"
                onClick={replayClick}
              >
                <ReplayIcon sx={{ fontSize: 14 }} />
              </AgentCardActionButton>
            )}
            {showReplay && (
              <AgentCardActionButton
                title={
                  status === 'running'
                    ? `Forcer la reprise depuis ${label}`
                    : `Relancer depuis ${label}`
                }
                onClick={replayClick}
              >
                <ReplayIcon sx={{ fontSize: 14 }} />
              </AgentCardActionButton>
            )}
          </Box>
        )}
      </Box>

      <Box
        sx={{
          minHeight: 24,
          px: 1.25,
          pb: 1,
          pt: 0,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 0.5,
          width: '100%',
          boxSizing: 'border-box',
        }}
      >
        {showCriticChip && (
          <Chip
            size="small"
            label={`${criticScore}/100`}
            color={criticApproved ? 'success' : criticScore >= 50 ? 'warning' : 'error'}
            sx={{ height: 18, fontSize: '0.65rem', '& .MuiChip-label': { px: 0.75 } }}
          />
        )}
        {showProgressChip && progress && (
          <AgentProgressChip progress={progress} status={status} />
        )}
      </Box>
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
  pipelineKickoff,
  projectId,
  selection,
  resumeTarget,
  onSelect,
  onReplay,
  onLaunch,
  onStop,
  actionLoading,
  criticReports,
  onRestartFromCritic,
  restartingReportId,
  pipelineProgress,
}: {
  steps: string[]
  iteration: number
  rowState: ReturnType<typeof getIterationRowState>
  agentRuns: AgentRun[]
  redisStatuses: Record<string, string> | undefined
  projectStatus: string
  pipelineKickoff?: PipelineKickoff | null
  projectId: string
  selection: PipelineSelection | undefined
  resumeTarget: ResumeTarget | null
  onSelect?: (sel: PipelineSelection) => void
  onReplay?: (step: string) => void
  onLaunch?: (step: string, iter?: number) => void
  onStop?: () => void
  actionLoading?: boolean
  criticReports: CriticReport[]
  onRestartFromCritic?: (reportId: string) => void
  restartingReportId?: string | null
  pipelineProgress?: PipelineProgressResponse
}) {
  const effectiveProjectStatus = getEffectiveProjectStatus(projectStatus, pipelineKickoff)
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
          pipelineKickoff,
        )
        const sel: PipelineSelection = { step, iteration }
        const isCritic = step === 'critic_agent'
        const isResume = isResumeTarget(step, iteration, resumeTarget)

        return (
          <Box key={step} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <AgentCard
              step={step}
              status={status}
              selected={selection ? matchesSelection(selection, step, iteration) : false}
              disabled={isPlannedRow}
              criticScore={isCritic && report ? report.global_score ?? undefined : undefined}
              criticApproved={isCritic && report ? report.decision === 'approve' : undefined}
              progress={pickAgentProgress(pipelineProgress, step, iteration)}
              onSelect={() => onSelect?.(sel)}
              showLaunch={isResume}
              onLaunch={isResume && onLaunch ? () => onLaunch(step, iteration) : undefined}
              showStop={effectiveProjectStatus === 'running'}
              onStop={onStop}
              actionLoading={actionLoading}
              onReplay={
                !isPlannedRow && !isResume && onReplay && status !== 'pending' && status !== 'planned'
                  ? () => onReplay(step)
                  : undefined
              }
              onRestartFromCritic={
                isCritic && report && onRestartFromCritic && restartingReportId !== report.id
                  ? () => onRestartFromCritic(report.id)
                  : undefined
              }
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
  if (rowState === 'stopped') return <Chip size="small" label="Interrompue" color="warning" />
  if (rowState === 'failed') return <Chip size="small" label="Échouée" color="error" />
  return <Chip size="small" label="Terminée" color="success" variant="outlined" />
}

function IterationRow({
  iter,
  rowState,
  agentRuns,
  redisStatuses,
  projectStatus,
  pipelineKickoff,
  projectId,
  selection,
  resumeTarget,
  onSelect,
  onReplay,
  onLaunch,
  onStop,
  actionLoading,
  criticReports,
  onRestartFromCritic,
  restartingReportId,
  pipelineProgress,
}: {
  iter: number
  rowState: ReturnType<typeof getIterationRowState>
  agentRuns: AgentRun[]
  redisStatuses: Record<string, string> | undefined
  projectStatus: string
  pipelineKickoff?: PipelineKickoff | null
  projectId: string
  selection: PipelineSelection | undefined
  resumeTarget: ResumeTarget | null
  onSelect?: (sel: PipelineSelection) => void
  onReplay?: (step: string) => void
  onLaunch?: (step: string, iter?: number) => void
  onStop?: () => void
  actionLoading?: boolean
  criticReports: CriticReport[]
  onRestartFromCritic?: (reportId: string) => void
  restartingReportId?: string | null
  pipelineProgress?: PipelineProgressResponse
}) {
  const steps = iter === 1
    ? ['narrator_agent', 'beat_planner_agent', 'media_agent', 'montage_planner_agent', 'editor_agent', 'subtitle_agent', 'critic_agent']
    : ['revision_agent', 'narrator_agent', 'beat_planner_agent', 'media_agent', 'montage_planner_agent', 'editor_agent', 'subtitle_agent', 'critic_agent']

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 2,
        border: rowState === 'active' ? '1px solid' : rowState === 'stopped' ? '1px solid' : '1px solid transparent',
        borderColor: rowState === 'active' ? 'info.main' : rowState === 'stopped' ? 'warning.main' : 'divider',
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
        pipelineKickoff={pipelineKickoff}
        projectId={projectId}
        selection={selection}
        resumeTarget={resumeTarget}
        onSelect={(sel) => onSelect?.(sel)}
        onReplay={onReplay}
        onLaunch={onLaunch}
        onStop={onStop}
        actionLoading={actionLoading}
        criticReports={criticReports}
        onRestartFromCritic={onRestartFromCritic}
        restartingReportId={restartingReportId}
        pipelineProgress={pipelineProgress}
      />
    </Box>
  )
}

interface Props {
  projectId: string
  isShort?: boolean
  /** Agents de préparation réellement concernés (selon le type de vidéo). */
  preparationAgents?: string[]
  /** Agents de post-production réellement concernés (selon le type de vidéo). */
  postProductionAgents?: string[]
  maxIterations: number
  projectStatus: string
  agentRuns: AgentRun[]
  criticReports: CriticReport[]
  pipelineKickoff?: PipelineKickoff | null
  onRunFrom?: (step: string) => void | Promise<void>
  onStop?: () => void
  onRestartFromCritic?: (reportId: string) => void
  selection?: PipelineSelection
  onSelect?: (sel: PipelineSelection | null) => void
  restartingReportId?: string | null
  actionLoading?: boolean
}

export default function PipelineVisualizer({
  projectId,
  isShort = false,
  preparationAgents,
  postProductionAgents,
  maxIterations,
  projectStatus,
  pipelineKickoff = null,
  agentRuns,
  criticReports,
  onRunFrom,
  onStop,
  onRestartFromCritic,
  selection,
  onSelect,
  restartingReportId,
  actionLoading = false,
}: Props) {
  const [confirmTarget, setConfirmTarget] = useState<ConfirmTarget | null>(null)
  const effectiveProjectStatus = getEffectiveProjectStatus(projectStatus, pipelineKickoff)

  const { data: redisStatuses } = useSWR<Record<string, string>>(
    `/api/v1/agents/status/${projectId}`,
    fetcher,
    { refreshInterval: isPipelineInFlight(projectStatus, pipelineKickoff) ? 2000 : 0 },
  )

  const { data: pipelineProgress } = useSWR<PipelineProgressResponse>(
    pipelineProgressUrl(projectId),
    fetcher,
    { refreshInterval: isPipelineInFlight(projectStatus, pipelineKickoff) ? 5000 : 0 },
  )

  const effectiveMax = effectiveMaxIterations(maxIterations, isShort)
  const criticApproved = isCriticLoopApproved(criticReports)

  // Listes d'agents réellement concernés (fournies par le plan ; sinon repli sur isShort).
  const prepAgents = preparationAgents
    ?? ['research_agent', 'outline_agent', 'scenario_agent', ...(!isShort ? ['hook_optimizer_agent'] : [])]
  const postAgents = postProductionAgents
    ?? (isShort ? ['short_editor_agent'] : ['clipper_agent', 'short_editor_agent'])

  const resumeTarget = getResumeStep(
    agentRuns,
    projectStatus,
    criticReports,
    isShort,
    pipelineKickoff,
    postAgents,
  )

  const researchStatus = deriveResearchStatus(agentRuns, redisStatuses, projectStatus, pipelineKickoff)
  const outlineStatus = deriveOutlineStatus(agentRuns, redisStatuses, projectStatus, pipelineKickoff)
  const scenarioStatus = deriveScenarioStatus(agentRuns, redisStatuses, projectStatus, pipelineKickoff)
  const hookOptimizerStatus = deriveHookOptimizerStatus(
    agentRuns,
    redisStatuses,
    projectStatus,
    scenarioStatus,
    pipelineKickoff,
    isShort,
  )
  const prepStatusFor: Record<string, AgentStatus> = {
    research_agent: researchStatus,
    outline_agent: outlineStatus,
    scenario_agent: scenarioStatus,
    hook_optimizer_agent: hookOptimizerStatus,
  }

  const openConfirm = (target: Omit<ConfirmTarget, 'mode'> & { mode?: ConfirmTarget['mode'] }) => {
    setConfirmTarget({ mode: target.mode ?? 'replay', ...target })
  }

  const handleLaunch = (step: string, iteration?: number) => {
    const isResume = isResumeTarget(step, iteration, resumeTarget)
    openConfirm({
      step,
      label: AGENT_LABELS[step] ?? step,
      iteration,
      mode: isResume ? 'resume' : 'replay',
    })
  }

  const handleConfirm = async () => {
    if (!confirmTarget || !onRunFrom) return
    try {
      await onRunFrom(confirmTarget.step)
      setConfirmTarget(null)
    } catch {
      // L'erreur est affichée par la page parente (actionError).
    }
  }

  const iterationRows = Array.from({ length: effectiveMax }, (_, i) => {
    const iter = i + 1
    return {
      iter,
      rowState: getIterationRowState(iter, criticReports, projectStatus, agentRuns, pipelineKickoff),
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
      pipelineKickoff={pipelineKickoff}
      projectId={projectId}
      selection={selection}
      resumeTarget={resumeTarget}
      onSelect={onSelect}
      onReplay={(step) =>
        openConfirm({ step, label: AGENT_LABELS[step] ?? step, iteration: iter, mode: 'replay' })
      }
      onLaunch={handleLaunch}
      onStop={onStop}
      actionLoading={actionLoading}
      criticReports={criticReports}
      onRestartFromCritic={onRestartFromCritic}
      restartingReportId={restartingReportId}
      pipelineProgress={pipelineProgress}
    />
  )

  const prepCardProps = (
    step: string,
    status: AgentStatus,
    disabled = false,
  ) => {
    const isResume = isResumeTarget(step, undefined, resumeTarget)
    return {
      step,
      status,
      disabled,
      progress: pickAgentProgress(pipelineProgress, step),
      selected: selection ? matchesSelection(selection, step) : false,
      onSelect: () => onSelect?.({ step }),
      showLaunch: isResume,
      onLaunch: isResume ? () => handleLaunch(step) : undefined,
      showStop: effectiveProjectStatus === 'running',
      onStop,
      actionLoading,
      onReplay:
        onRunFrom && !isResume && status !== 'pending' && status !== 'planned'
          ? () => openConfirm({ step, label: AGENT_LABELS[step] ?? step, mode: 'replay' })
          : undefined,
    }
  }

  return (
    <>
      {resumeTarget && ['stopped', 'failed'].includes(projectStatus) && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Pipeline interrompu — reprenez à partir de{' '}
          <strong>{resumeTarget.label}</strong>
          {resumeTarget.iteration != null && ` (itération ${resumeTarget.iteration})`}.
        </Alert>
      )}
      <Stack spacing={2.5}>
        {/* Préparation */}
        <Box>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
            Préparation
          </Typography>
          <Box sx={{ display: 'inline-flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            {prepAgents.map((step, idx) => {
              const status = prepStatusFor[step] ?? 'pending'
              const disabled =
                step === 'hook_optimizer_agent'
                && scenarioStatus !== 'success'
                && scenarioStatus !== 'running'
                && status === 'planned'
              return (
                <Box key={step} sx={{ display: 'inline-flex', alignItems: 'center', gap: 1 }}>
                  {idx > 0 && <ArrowForwardIcon fontSize="small" color="disabled" />}
                  <AgentCard {...prepCardProps(step, status, disabled)} />
                </Box>
              )
            })}
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

        {/* Post-production — uniquement les agents que ce type de vidéo produit. */}
        {postAgents.length > 0 && (
          <Box>
            <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
              Post-production
              {!criticApproved && effectiveProjectStatus !== 'running' && (
                <Typography component="span" variant="caption" sx={{ ml: 1 }}>
                  — après approbation critique
                </Typography>
              )}
            </Typography>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1, alignItems: 'center' }}>
              {postAgents.map((step, idx) => (
                <Box key={step} sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  {idx > 0 && <ArrowForwardIcon sx={{ color: 'text.disabled', fontSize: 16 }} />}
                  <AgentCard
                    {...prepCardProps(
                      step,
                      derivePostProdStatus(
                        step,
                        agentRuns,
                        redisStatuses,
                        projectStatus,
                        criticApproved,
                        pipelineKickoff,
                      ),
                      !criticApproved && effectiveProjectStatus !== 'running',
                    )}
                  />
                </Box>
              ))}
            </Box>
          </Box>
        )}
      </Stack>

      <Dialog open={!!confirmTarget} onClose={() => setConfirmTarget(null)} maxWidth="xs" fullWidth>
        <DialogTitle>
          {confirmTarget?.mode === 'resume' ? 'Reprendre' : 'Relancer'} « {confirmTarget?.label} » ?
          {confirmTarget?.iteration != null && ` (itération ${confirmTarget.iteration})`}
        </DialogTitle>
        <DialogContent>
          <Typography variant="body2" sx={{ mb: 1.5 }}>
            {confirmTarget?.mode === 'resume'
              ? 'Le pipeline reprendra à cette étape. Les artefacts suivants seront régénérés si nécessaire :'
              : 'Les données suivantes seront supprimées et recréées :'}
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
          <Button
            variant="contained"
            color={confirmTarget?.mode === 'resume' ? 'primary' : 'warning'}
            onClick={() => void handleConfirm()}
            disabled={actionLoading}
          >
            {confirmTarget?.mode === 'resume' ? 'Reprendre' : 'Confirmer le relancement'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
