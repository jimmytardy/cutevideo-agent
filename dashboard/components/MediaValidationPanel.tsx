'use client'

import { useEffect, useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Divider from '@mui/material/Divider'
import {
  fetcher,
  fetchProjectMediaValidation,
  updateProjectMediaValidation,
  regenerateProjectMediaValidation,
  type MediaValidationBrief,
  type Scenario,
} from '@/lib/api'

interface Props {
  projectId: string
  projectStatus: string
  scenario?: Scenario | null
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

export default function MediaValidationPanel({ projectId, projectStatus, scenario }: Props) {
  const { data: brief, mutate, isLoading, error } = useSWR<MediaValidationBrief>(
    `/api/v1/projects/${projectId}/media-validation`,
    () => fetchProjectMediaValidation(projectId),
    { refreshInterval: projectStatus === 'running' ? 5000 : 0 },
  )

  const [mustInclude, setMustInclude] = useState('')
  const [mustExclude, setMustExclude] = useState('')
  const [validationPrompt, setValidationPrompt] = useState('')
  const [minScore, setMinScore] = useState('')
  const [saving, setSaving] = useState(false)
  const [regenerating, setRegenerating] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  useEffect(() => {
    if (!brief) return
    const ov = brief.override
    setMustInclude((ov?.must_include ?? []).join(', '))
    setMustExclude((ov?.must_exclude ?? []).join(', '))
    setValidationPrompt(ov?.validation_prompt ?? '')
    setMinScore(ov?.min_relevance_score != null ? String(ov.min_relevance_score) : '')
  }, [brief])

  const canEdit = ['pending', 'stopped', 'failed'].includes(projectStatus)

  const handleSaveOverride = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      const parseList = (s: string) =>
        s.split(',').map((x) => x.trim()).filter(Boolean)
      const parsedMin = minScore.trim() ? parseInt(minScore, 10) : null
      await updateProjectMediaValidation(projectId, {
        must_include: parseList(mustInclude),
        must_exclude: parseList(mustExclude),
        validation_prompt: validationPrompt.trim() || null,
        min_relevance_score: Number.isFinite(parsedMin) ? parsedMin : null,
      })
      await mutate()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Erreur sauvegarde')
    } finally {
      setSaving(false)
    }
  }

  const handleRegenerate = async () => {
    setRegenerating(true)
    setSaveError(null)
    try {
      await regenerateProjectMediaValidation(projectId)
      await mutate()
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Erreur régénération')
    } finally {
      setRegenerating(false)
    }
  }

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

  return (
    <Box sx={{ mb: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
        <Typography variant="h6">Validation média</Typography>
        <Chip label={brief.source} size="small" variant="outlined" />
        <Chip
          label={`niche: ${brief.niche_risk}`}
          size="small"
          color={brief.niche_risk === 'high' ? 'warning' : 'default'}
        />
        <Chip label={`seuil ${brief.min_relevance_score}`} size="small" />
      </Box>

      <Typography variant="subtitle2" gutterBottom>
        Sujet précis : {brief.subject_entity || '—'} ({brief.subject_type})
      </Typography>

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
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2, fontStyle: 'italic' }}>
          {brief.validation_prompt}
        </Typography>
      )}

      {scenario?.segments && scenario.segments.length > 0 && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Par segment</Typography>
          {scenario.segments.map((seg) => (
            <Box key={seg.order} sx={{ mb: 1 }}>
              <Typography variant="body2">
                #{seg.order} {seg.title}
                {seg.search_keywords?.length ? ` — ${seg.search_keywords.slice(0, 4).join(', ')}` : ''}
              </Typography>
            </Box>
          ))}
        </>
      )}

      {canEdit && (
        <>
          <Divider sx={{ my: 2 }} />
          <Typography variant="subtitle2" sx={{ mb: 1 }}>Override projet (optionnel)</Typography>
          <TextField
            fullWidth
            label="Doit montrer (virgules)"
            value={mustInclude}
            onChange={(e) => setMustInclude(e.target.value)}
            sx={{ mb: 1.5 }}
            size="small"
          />
          <TextField
            fullWidth
            label="Ne doit pas montrer (virgules)"
            value={mustExclude}
            onChange={(e) => setMustExclude(e.target.value)}
            sx={{ mb: 1.5 }}
            size="small"
          />
          <TextField
            fullWidth
            label="Prompt de validation additionnel"
            multiline
            rows={3}
            value={validationPrompt}
            onChange={(e) => setValidationPrompt(e.target.value)}
            sx={{ mb: 1.5 }}
            size="small"
          />
          <TextField
            label="Seuil min (0-100)"
            type="number"
            value={minScore}
            onChange={(e) => setMinScore(e.target.value)}
            sx={{ mb: 2, width: 160 }}
            size="small"
            inputProps={{ min: 0, max: 100 }}
          />
          <Stack direction="row" gap={1}>
            <Button variant="contained" onClick={handleSaveOverride} disabled={saving}>
              {saving ? 'Enregistrement…' : 'Enregistrer override'}
            </Button>
            <Button variant="outlined" onClick={handleRegenerate} disabled={regenerating}>
              {regenerating ? 'Régénération…' : 'Régénérer le brief'}
            </Button>
          </Stack>
        </>
      )}

      {saveError && <Alert severity="error" sx={{ mt: 2 }}>{saveError}</Alert>}
    </Box>
  )
}
