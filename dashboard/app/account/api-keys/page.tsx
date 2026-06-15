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
import List from '@mui/material/List'
import ListItem from '@mui/material/ListItem'
import ListItemText from '@mui/material/ListItemText'
import Link from '@mui/material/Link'
import ListItemIcon from '@mui/material/ListItemIcon'
import CheckCircleOutlineIcon from '@mui/icons-material/CheckCircleOutline'
import HighlightOffOutlinedIcon from '@mui/icons-material/HighlightOffOutlined'
import AppShell from '@/components/AppShell'
import AuthGuard from '@/components/AuthGuard'
import { authHeaders, fetcher } from '@/lib/api'
import {
  API_KEY_PROVIDERS,
  getApiKeyProvider,
  getApiKeyProviderLabel,
  type ApiKeyProviderId,
} from '@/lib/apiKeyProviders'

const BASE = '/api/v1'

type ApiKeyStatus = {
  provider: string
  configured: boolean
  key_hint?: string | null
}

function KeyConfiguredIcon({ configured }: { configured: boolean }) {
  return configured ? (
    <CheckCircleOutlineIcon fontSize="small" color="success" aria-label="Clé enregistrée" />
  ) : (
    <HighlightOffOutlinedIcon fontSize="small" color="disabled" aria-label="Clé non enregistrée" />
  )
}

export default function ApiKeysPage() {
  const { data: keys, mutate } = useSWR<ApiKeyStatus[]>(`${BASE}/me/api-keys`, fetcher)
  const [provider, setProvider] = useState<ApiKeyProviderId>('gemini')
  const [apiKey, setApiKey] = useState('')
  const [message, setMessage] = useState<string | null>(null)

  const selectedProvider = getApiKeyProvider(provider)
  const configuredByProvider = new Map(
    (Array.isArray(keys) ? keys : []).map((k) => [k.provider, k.configured]),
  )
  const configuredKeys = Array.isArray(keys) ? keys.filter((k) => k.configured) : []
  const unconfiguredKeys = Array.isArray(keys) ? keys.filter((k) => !k.configured) : []

  const saveKey = async () => {
    setMessage(null)
    const res = await fetch(`${BASE}/me/api-keys/${provider}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: JSON.stringify({ api_key: apiKey }),
    })
    if (!res.ok) {
      const body = await res.json().catch(() => ({}))
      setMessage(body.detail || 'Erreur')
      return
    }
    setApiKey('')
    setMessage('Clé enregistrée')
    mutate()
  }

  return (
    <AuthGuard>
      <AppShell>
        <Typography variant="h5" fontWeight={700} gutterBottom>
          Clés API personnelles
        </Typography>
        <Typography color="text.secondary" paragraph>
          Les clés payantes sont optionnelles. Sans clé Anthropic, les agents utilisent Gemini gratuit.
        </Typography>
        {message && <Alert severity="info" sx={{ mb: 2 }}>{message}</Alert>}

        {Array.isArray(keys) && (
          <Card sx={{ mb: 3, maxWidth: 720 }}>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                Clés enregistrées
              </Typography>
              {configuredKeys.length === 0 ? (
                <Typography variant="body2" color="text.secondary">
                  Aucune clé enregistrée pour le moment.
                </Typography>
              ) : (
                <List dense disablePadding>
                  {configuredKeys.map((k) => (
                    <ListItem key={k.provider} disableGutters sx={{ py: 0.75 }}>
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
                          </Box>
                        }
                      />
                    </ListItem>
                  ))}
                </List>
              )}
            </CardContent>
          </Card>
        )}

        <Typography variant="subtitle1" fontWeight={600} gutterBottom>
          Ajouter ou remplacer une clé
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', maxWidth: 720 }}>
          <TextField
            select
            label="Service"
            value={provider}
            onChange={(e) => setProvider(e.target.value as ApiKeyProviderId)}
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
            {API_KEY_PROVIDERS.map((p) => (
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
          <Button variant="contained" onClick={saveKey} disabled={!apiKey.trim()} sx={{ alignSelf: 'flex-start' }}>
            Enregistrer
          </Button>
        </Box>

        {selectedProvider && (
          <Card variant="outlined" sx={{ mt: 2, maxWidth: 720, bgcolor: 'action.hover' }}>
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
          <Box sx={{ mt: 3, maxWidth: 720 }}>
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
      </AppShell>
    </AuthGuard>
  )
}
