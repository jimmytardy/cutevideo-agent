'use client'

import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import useSWR from 'swr'
import Link from 'next/link'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Table from '@mui/material/Table'
import TableHead from '@mui/material/TableHead'
import TableBody from '@mui/material/TableBody'
import TableRow from '@mui/material/TableRow'
import TableCell from '@mui/material/TableCell'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Chip from '@mui/material/Chip'
import Collapse from '@mui/material/Collapse'
import IconButton from '@mui/material/IconButton'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import {
  type AgentLlmConfig,
  type AgentLlmPreference,
  type LlmProvider,
  type LlmTier,
  buildPreferencesMap,
  getAgentInfo,
  getAgentLabel,
  groupConfigurableAgents,
  isLinkedAgent,
  allowedProvidersFor,
  defaultModelForAgent,
  modelOptionsForAgent,
  normalizePreference,
  resolvePreferenceAgent,
} from '@/lib/agentLlm'
import { authHeaders, fetcher } from '@/lib/api'

const BASE = '/api/v1'

interface AgentLlmRowProps {
  agentName: string
  pref: AgentLlmPreference
  recommendation: string
  expanded: boolean
  readOnly: boolean
  linkedToLabel?: string
  hasGeminiKey: boolean
  hasAnthropicKey: boolean
  onToggleDetails: () => void
  onProviderChange: (provider: LlmProvider) => void
  onTierChange: (tier: LlmTier) => void
  onModelChange: (model: string) => void
}

function AgentLlmRow({
  agentName,
  pref,
  recommendation,
  expanded,
  readOnly,
  linkedToLabel,
  hasGeminiKey,
  hasAnthropicKey,
  onToggleDetails,
  onProviderChange,
  onTierChange,
  onModelChange,
}: AgentLlmRowProps) {
  const info = getAgentInfo(agentName)
  const sourceAgent = resolvePreferenceAgent(agentName)
  const providers = allowedProvidersFor(sourceAgent)
  const models = modelOptionsForAgent(sourceAgent, pref.provider, pref.tier)
  const controlsDisabled = readOnly || !hasGeminiKey
  const geminiOnly = providers.length === 1 && providers[0] === 'gemini'

  return (
    <>
      <TableRow hover>
        <TableCell sx={{ minWidth: 240 }}>
          <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5 }}>
            <IconButton
              size="small"
              aria-label={expanded ? 'Masquer les tâches' : 'Afficher les tâches'}
              aria-expanded={expanded}
              onClick={onToggleDetails}
              sx={{
                mt: -0.25,
                transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
                transition: 'transform 0.2s',
              }}
            >
              <ExpandMoreIcon fontSize="small" />
            </IconButton>
            <Box
              component="button"
              type="button"
              onClick={onToggleDetails}
              sx={{
                border: 0,
                p: 0,
                m: 0,
                bgcolor: 'transparent',
                textAlign: 'left',
                cursor: 'pointer',
                color: 'inherit',
              }}
            >
              <Typography variant="body2" fontWeight={600}>
                {info.label}
              </Typography>
              <Typography
                variant="caption"
                color="text.secondary"
                display="block"
                sx={{ mt: 0.25 }}
              >
                Conseillé : {recommendation}
              </Typography>
              <Typography variant="caption" color="text.secondary" display="block">
                {info.title}
              </Typography>
              {linkedToLabel && (
                <Chip
                  label={`Identique au ${linkedToLabel}`}
                  size="small"
                  variant="outlined"
                  sx={{ mt: 0.75 }}
                />
              )}
            </Box>
          </Box>
        </TableCell>
        <TableCell sx={{ minWidth: 150 }}>
          <TextField
            select
            size="small"
            fullWidth
            value={pref.provider}
            onChange={(e) => onProviderChange(e.target.value as LlmProvider)}
            disabled={controlsDisabled}
          >
            <MenuItem value="gemini">Gemini</MenuItem>
            {!geminiOnly && (
              <MenuItem value="anthropic" disabled={!hasAnthropicKey || readOnly}>
                Anthropic
              </MenuItem>
            )}
          </TextField>
        </TableCell>
        <TableCell sx={{ minWidth: 130 }}>
          {pref.provider === 'gemini' ? (
            <TextField
              select
              size="small"
              fullWidth
              value={pref.tier}
              onChange={(e) => onTierChange(e.target.value as LlmTier)}
              disabled={controlsDisabled}
            >
              <MenuItem value="free">Gratuit</MenuItem>
              <MenuItem value="paid" disabled={!hasGeminiKey || readOnly}>
                Payant
              </MenuItem>
            </TextField>
          ) : (
            <Chip label="Payant" size="small" variant="outlined" />
          )}
        </TableCell>
        <TableCell sx={{ minWidth: 220 }}>
          <TextField
            select
            size="small"
            fullWidth
            value={pref.model}
            onChange={(e) => onModelChange(e.target.value)}
            disabled={controlsDisabled}
          >
            {models.map((m) => (
              <MenuItem key={m.value} value={m.value}>
                {m.label}
              </MenuItem>
            ))}
          </TextField>
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell colSpan={4} sx={{ py: 0, borderBottom: expanded ? undefined : 0 }}>
          <Collapse in={expanded} timeout="auto" unmountOnExit>
            <Box sx={{ py: 1.5, pl: 5, pr: 1 }}>
              <Typography
                variant="caption"
                color="text.secondary"
                fontWeight={600}
                display="block"
                sx={{ mb: 0.5 }}
              >
                Tâches
              </Typography>
              <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
                {info.tasks.map((task) => (
                  <Typography
                    key={task}
                    component="li"
                    variant="body2"
                    color="text.secondary"
                    sx={{ mb: 0.25 }}
                  >
                    {task}
                  </Typography>
                ))}
              </Box>
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </>
  )
}

export default function AgentLlmConfigPanel() {
  const { data, isLoading, mutate } = useSWR<AgentLlmConfig>(`${BASE}/me/agent-llm`, fetcher)
  const [preferences, setPreferences] = useState<Record<string, AgentLlmPreference>>({})
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<{ severity: 'success' | 'error' | 'info'; text: string } | null>(
    null,
  )
  const [expandedAgents, setExpandedAgents] = useState<Record<string, boolean>>({})
  const saveRequestId = useRef(0)

  const toggleAgentDetails = (agentName: string) => {
    setExpandedAgents((prev) => ({ ...prev, [agentName]: !prev[agentName] }))
  }

  useEffect(() => {
    if (!data) return
    setPreferences(buildPreferencesMap(data.agents, data.preferences))
  }, [data])

  useEffect(() => {
    if (message?.severity !== 'success') return
    const timer = window.setTimeout(() => setMessage(null), 2000)
    return () => window.clearTimeout(timer)
  }, [message])

  const persistPreferences = useCallback(
    async (nextPreferences: Record<string, AgentLlmPreference>) => {
      if (!data?.has_gemini_key) return

      const requestId = ++saveRequestId.current
      setSaving(true)
      setMessage(null)
      try {
        const res = await fetch(`${BASE}/me/agent-llm`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json', ...authHeaders() },
          body: JSON.stringify({ preferences: nextPreferences }),
        })
        if (requestId !== saveRequestId.current) return
        if (!res.ok) {
          const body = await res.json().catch(() => ({}))
          setMessage({
            severity: 'error',
            text: body.detail || 'Erreur lors de la sauvegarde',
          })
          return
        }
        await mutate()
        setMessage({ severity: 'success', text: 'Configuration enregistrée' })
      } finally {
        if (requestId === saveRequestId.current) {
          setSaving(false)
        }
      }
    },
    [data?.has_gemini_key, mutate],
  )

  const applyAgentChange = useCallback(
    (agentName: string, patch: Partial<AgentLlmPreference>) => {
      setPreferences((prev) => {
        const current = prev[agentName]
        if (!current) return prev
        const nextPref = normalizePreference({ ...current, ...patch }, agentName)
        const updated = { ...prev, [agentName]: nextPref }
        void persistPreferences(updated)
        return updated
      })
    },
    [persistPreferences],
  )

  const handleProviderChange = (agentName: string, provider: LlmProvider) => {
    const tier: LlmTier = provider === 'anthropic' ? 'paid' : 'free'
    const model = defaultModelForAgent(agentName, provider, tier)
    applyAgentChange(agentName, { provider, tier, model })
  }

  const handleTierChange = (agentName: string, tier: LlmTier) => {
    const current = preferences[agentName]
    if (!current || current.provider !== 'gemini') return
    const model = defaultModelForAgent(agentName, 'gemini', tier)
    applyAgentChange(agentName, { tier, model })
  }

  if (isLoading) {
    return <CircularProgress />
  }

  if (!data) {
    return <Alert severity="error">Impossible de charger la configuration des modèles.</Alert>
  }

  const agentGroups = groupConfigurableAgents(data.agents)

  return (
    <Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Choisissez quel fournisseur et quel modèle pilote chaque agent. Chaque modification est
        enregistrée automatiquement. Sans clé personnelle, Gemini gratuit de la plateforme est
        utilisé par défaut.
      </Typography>

      {!data.has_gemini_key && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Pour personnaliser les modèles, enregistrez d&apos;abord une clé Gemini dans{' '}
          <Link href="/account/api-keys">Clés API</Link>.
        </Alert>
      )}

      {!data.has_anthropic_key && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Les modèles Anthropic nécessitent une clé Anthropic dans{' '}
          <Link href="/account/api-keys">Clés API</Link>.
        </Alert>
      )}

      <Card>
        <CardContent sx={{ p: 0 }}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Agent</TableCell>
                <TableCell>Fournisseur</TableCell>
                <TableCell>Tarif</TableCell>
                <TableCell>Modèle</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {agentGroups.map((group, groupIndex) => (
                <Fragment key={group.id}>
                  <TableRow>
                    <TableCell
                      colSpan={4}
                      sx={{
                        bgcolor: 'action.hover',
                        py: 1.5,
                        borderTop: groupIndex > 0 ? 1 : 0,
                        borderColor: 'divider',
                      }}
                    >
                      <Typography variant="subtitle2" fontWeight={700}>
                        {group.label}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {group.description}
                      </Typography>
                    </TableCell>
                  </TableRow>
                  {group.agents.map((agentName) => {
                    const linkedAgents = data.linked_agents ?? {}
                    const sourceAgent = resolvePreferenceAgent(agentName, linkedAgents)
                    const pref = preferences[sourceAgent]
                    if (!pref) return null
                    const linked = isLinkedAgent(agentName, linkedAgents)
                    return (
                      <AgentLlmRow
                        key={agentName}
                        agentName={agentName}
                        pref={pref}
                        recommendation={data.recommendations[agentName] ?? data.recommendations[sourceAgent] ?? '—'}
                        expanded={expandedAgents[agentName] ?? false}
                        readOnly={linked}
                        linkedToLabel={linked ? getAgentLabel(sourceAgent) : undefined}
                        hasGeminiKey={data.has_gemini_key}
                        hasAnthropicKey={data.has_anthropic_key}
                        onToggleDetails={() => toggleAgentDetails(agentName)}
                        onProviderChange={(provider) => handleProviderChange(sourceAgent, provider)}
                        onTierChange={(tier) => handleTierChange(sourceAgent, tier)}
                        onModelChange={(model) => applyAgentChange(sourceAgent, { model })}
                      />
                    )
                  })}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {(saving || message) && (
        <Box sx={{ mt: 2, display: 'flex', gap: 1.5, alignItems: 'center', minHeight: 40 }}>
          {saving ? (
            <>
              <CircularProgress size={16} />
              <Typography variant="body2" color="text.secondary">
                Enregistrement…
              </Typography>
            </>
          ) : message ? (
            <Alert severity={message.severity} sx={{ flex: 1, py: 0.25 }}>
              {message.text}
            </Alert>
          ) : null}
        </Box>
      )}
    </Box>
  )
}
