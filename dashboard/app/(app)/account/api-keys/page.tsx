'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import Button from '@mui/material/Button'
import MenuItem from '@mui/material/MenuItem'
import Alert from '@mui/material/Alert'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import IconButton from '@mui/material/IconButton'
import CircularProgress from '@mui/material/CircularProgress'
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Link from '@mui/material/Link'
import ListItemIcon from '@mui/material/ListItemIcon'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import HighlightOffOutlinedIcon from '@mui/icons-material/HighlightOffOutlined'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import { PageContainer, PageHeader, PageSection, useConfirmDialog } from '@/components/layout'
import { API_BASE, deleteApiKey, fetcher, saveApiKey } from '@/lib/api'
import { useMe } from '@/lib/hooks'
import {
  API_KEY_PROVIDERS,
  getApiKeyProvider,
  getApiKeyProviderLabel,
  type ApiKeyProviderId,
} from '@/lib/apiKeyProviders'


type ApiKeyStatus = {
  provider: string
  configured: boolean
  key_hint?: string | null
  metadata?: Record<string, unknown> | null
}

type KeyHealthStatus = 'ok' | 'invalid' | 'expired' | 'no_credit' | 'quota' | 'unavailable'

type ApiKeyHealth = {
  provider: string
  status: KeyHealthStatus
  detail: string
}

const HEALTH_LABELS: Record<KeyHealthStatus, { label: string; color: 'success' | 'error' | 'warning' | 'default' }> = {
  ok: { label: 'Fonctionne', color: 'success' },
  invalid: { label: 'Invalide', color: 'error' },
  expired: { label: 'Expirée', color: 'error' },
  no_credit: { label: 'Crédit épuisé', color: 'error' },
  quota: { label: 'Quota atteint', color: 'warning' },
  unavailable: { label: 'Non vérifiable', color: 'default' },
}

function KeyHealthChip({ health, checking }: { health?: ApiKeyHealth; checking: boolean }) {
  if (!health) {
    return checking ? <CircularProgress size={14} aria-label="Vérification en cours" /> : null
  }
  const { label, color } = HEALTH_LABELS[health.status] ?? HEALTH_LABELS.unavailable
  return <Chip label={label} size="small" color={color} variant={health.status === 'ok' ? 'outlined' : 'filled'} />
}

function KeyConfiguredIcon({ configured }: { configured: boolean }) {
  return configured ? (
    <CheckCircleOutlineIcon fontSize="small" color="success" aria-label="Clé enregistrée" />
  ) : (
    <HighlightOffOutlinedIcon fontSize="small" color="disabled" aria-label="Clé non enregistrée" />
  )
}

export default function ApiKeysPage() {
  const { data: keys, mutate } = useSWR<ApiKeyStatus[]>(`${API_BASE}/me/api-keys`, fetcher)
  const { data: me } = useMe()
  const providers = API_KEY_PROVIDERS.filter((p) => !p.adminOnly || me?.is_admin)
  // Chaque vérification interroge les fournisseurs : pas de revalidation automatique au focus.
  const {
    data: health,
    isValidating: checking,
    mutate: recheck,
  } = useSWR<ApiKeyHealth[]>(`${API_BASE}/me/api-keys/health`, fetcher, {
    revalidateOnFocus: false,
    revalidateOnReconnect: false,
  })
  const healthByProvider = new Map((Array.isArray(health) ? health : []).map((h) => [h.provider, h]))
  const [provider, setProvider] = useState<ApiKeyProviderId>('gemini')
  const [apiKey, setApiKey] = useState('')
  const [metadata, setMetadata] = useState<Record<string, string>>({})
  const [message, setMessage] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const { confirm, dialog } = useConfirmDialog()

  const selectedProvider = getApiKeyProvider(provider)
  const metadataFields = selectedProvider?.metadataFields ?? []
  const missingRequired = metadataFields.some((f) => f.required && !metadata[f.key]?.trim())

  const selectProvider = (id: ApiKeyProviderId) => {
    setProvider(id)
    // Champs complémentaires préremplis avec ceux déjà enregistrés (région, page…).
    const stored = (Array.isArray(keys) ? keys : []).find((k) => k.provider === id)?.metadata ?? {}
    setMetadata(Object.fromEntries(Object.entries(stored).map(([k, v]) => [k, String(v ?? '')])))
  }
  const configuredByProvider = new Map(
    (Array.isArray(keys) ? keys : []).map((k) => [k.provider, k.configured]),
  )
  const configuredKeys = Array.isArray(keys) ? keys.filter((k) => k.configured) : []
  const unconfiguredKeys = Array.isArray(keys) ? keys.filter((k) => !k.configured) : []

  const saveKey = async () => {
    setMessage(null)
    try {
      const filled = Object.fromEntries(
        metadataFields
          .map((f) => [f.key, metadata[f.key]?.trim() ?? ''] as const)
          .filter(([, v]) => v),
      )
      await saveApiKey(provider, apiKey, metadataFields.length ? filled : undefined)
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Erreur')
      return
    }
    setApiKey('')
    setMessage('Clé enregistrée')
    mutate()
    recheck()
  }

  const removeKey = async (id: string) => {
    const label = getApiKeyProviderLabel(id)
    const ok = await confirm({
      title: 'Supprimer la clé',
      message: `Supprimer la clé ${label} ? Les vidéos, agents et publications qui en dépendent ne pourront plus l’utiliser. Cette action est irréversible.`,
      confirmLabel: 'Supprimer',
      confirmColor: 'error',
    })
    if (!ok) return
    setMessage(null)
    setDeleting(id)
    try {
      await deleteApiKey(id)
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Erreur')
      return
    } finally {
      setDeleting(null)
    }
    // Le cache est mis à jour tout de suite : ni la liste ni le formulaire ne doivent ressortir l'ancienne clé,
    // et une clé ressaisie ne doit pas afficher l'ancien état de santé.
    mutate((current) =>
      current?.map((k) => (k.provider === id ? { ...k, configured: false, key_hint: null, metadata: null } : k)),
    )
    recheck((current) => current?.filter((h) => h.provider !== id), { revalidate: false })
    if (id === provider) {
      setApiKey('')
      setMetadata({})
    }
    setMessage(`Clé ${label} supprimée`)
  }

  return (
    <PageContainer maxWidth="md">
      <PageHeader
        title="Clés API personnelles"
        description="Vos vidéos, agents et publications utilisent uniquement ces clés : aucune clé de la plateforme n’est partagée. La clé Anthropic est requise pour créer des vidéos."
      />
      {dialog}
      {message && <Alert severity="info" sx={{ mb: 2 }}>{message}</Alert>}

      {Array.isArray(keys) && (
        <PageSection title="Clés enregistrées">
          <Card sx={{ mb: 3 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1, mb: 1 }}>
                <Typography variant="h6">Clés enregistrées</Typography>
                {configuredKeys.length > 0 && (
                  <Button size="small" onClick={() => recheck()} disabled={checking}>
                    {checking ? 'Vérification…' : 'Revérifier'}
                  </Button>
                )}
              </Box>
              {configuredKeys.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  Aucune clé enregistrée pour le moment.
                </Typography>
              ) : (
                <List dense disablePadding>
                  {configuredKeys.map((k) => (
                    <ListItem
                      key={k.provider}
                      disableGutters
                      sx={{ py: 0.75 }}
                      secondaryAction={
                        <IconButton
                          edge="end"
                          size="small"
                          color="error"
                          onClick={() => removeKey(k.provider)}
                          disabled={deleting === k.provider}
                          aria-label={`Supprimer la clé ${getApiKeyProviderLabel(k.provider)}`}
                        >
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      }
                    >
                      <ListItemText
                        primary={
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                            <Chip
                              label={getApiKeyProviderLabel(k.provider)}
                              size="small"
                              color="primary"
                              variant="outlined"
                            />
                            <Typography
                              component="span"
                              variant="body2"
                              sx={{ fontFamily: 'monospace', color: 'text.secondary' }}
                            >
                              {k.key_hint || '••••••••'}
                            </Typography>
                            <KeyHealthChip health={healthByProvider.get(k.provider)} checking={checking} />
                          </Box>
                        }
                        secondary={
                          healthByProvider.get(k.provider)?.status !== 'ok'
                            ? healthByProvider.get(k.provider)?.detail
                            : undefined
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        </PageSection>
      )}

      <PageSection title="Ajouter ou remplacer une clé">
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <TextField
            select
            label="Service"
            value={provider}
            onChange={(e) => selectProvider(e.target.value as ApiKeyProviderId)}
            sx={{ minWidth: 280 }}
            SelectProps={{
              renderValue: (value) => {
                const id = value as ApiKeyProviderId
                return (
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <KeyConfiguredIcon configured={configuredByProvider.get(id) ?? false} />
                    {getApiKeyProviderLabel(id)}
                  </Box>
                )
              },
            }}
          >
            {providers.map((p) => (
              <MenuItem key={p.id} value={p.id}>
                <ListItemIcon sx={{ minWidth: 32 }}>
                  <KeyConfiguredIcon configured={configuredByProvider.get(p.id) ?? false} />
                </ListItemIcon>
                {p.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label={selectedProvider?.keyFieldLabel ?? 'Clé API'}
            type={provider === 'gcp' ? 'text' : 'password'}
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            fullWidth
            multiline={provider === 'gcp'}
            minRows={provider === 'gcp' ? 3 : undefined}
            sx={{ flex: 1, minWidth: 240 }}
          />
          {metadataFields.map((field) => (
            <TextField
              key={field.key}
              label={field.label}
              placeholder={field.placeholder}
              required={field.required}
              value={metadata[field.key] ?? ''}
              onChange={(e) => setMetadata((prev) => ({ ...prev, [field.key]: e.target.value }))}
              sx={{ minWidth: 200 }}
            />
          ))}
          <Button
            variant="contained"
            onClick={saveKey}
            disabled={!apiKey.trim() || missingRequired}
            sx={{ alignSelf: 'flex-start' }}
          >
            Enregistrer
          </Button>
        </Box>

        {selectedProvider && (
          <Card variant="outlined" sx={{ mt: 2, bgcolor: 'action.hover' }}>
            <CardContent>
              <Typography variant="subtitle2" fontWeight={600} gutterBottom>
                {selectedProvider.tutorialTitle}
              </Typography>
              <Typography variant="body2" color="text.secondary" paragraph sx={{ mb: 1.5 }}>
                {selectedProvider.shortDescription}
              </Typography>
              <Box component="ol" sx={{ m: 0, pl: 2.5 }}>
                {selectedProvider.steps.map((step) => (
                  <Typography component="li" variant="body2" color="text.secondary" key={step} sx={{ mb: 0.75 }}>
                    {step}
                  </Typography>
                ))}
              </Box>
              <Link href={selectedProvider.docUrl} target="_blank" rel="noopener" variant="body2" sx={{ mt: 1, display: 'inline-block' }}>
                {selectedProvider.docLabel} ↗
              </Link>
            </CardContent>
          </Card>
        )}

        {unconfiguredKeys.length > 0 && (
          <Box sx={{ mt: 3 }}>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              Services sans clé
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {unconfiguredKeys.map((k) => (
                <Chip key={k.provider} label={getApiKeyProviderLabel(k.provider)} size="small" variant="outlined" />
              ))}
            </Box>
          </Box>
        )}
      </PageSection>
    </PageContainer>
  )
}
