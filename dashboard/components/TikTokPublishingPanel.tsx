'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Link from 'next/link'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'

import {
  connectTikTok,
  fetchChannelIntegrations,
  fetcher,
  setTikTokProvider,
  type ChannelIntegrations,
  type TikTokProvider,
} from '@/lib/api'

const PROVIDERS: { value: TikTokProvider; label: string; help: string; keyProvider?: string }[] = [
  {
    value: 'postforme',
    label: 'Post for Me',
    help: 'Appli TikTok auditée de Post for Me : publications publiques, comptes illimités (~10 $/mois pour 1 000 posts).',
    keyProvider: 'postforme',
  },
  {
    value: 'zernio',
    label: 'Zernio',
    help: 'Appli TikTok de Zernio : 2 comptes gratuits, puis facturation par compte connecté.',
    keyProvider: 'zernio',
  },
  {
    value: 'composio',
    label: 'Composio (historique)',
    help: 'Clé Composio de la plateforme (.env). Les vidéos peuvent rester privées si l’appli n’est pas auditée.',
  },
]

type ApiKeyStatus = { provider: string; configured: boolean }

export default function TikTokPublishingPanel({ channelId }: { channelId: string }) {
  const { data: integrations, mutate } = useSWR<ChannelIntegrations>(
    `/api/v1/channels/${channelId}/integrations`,
    () => fetchChannelIntegrations(channelId),
  )
  const { data: keys } = useSWR<ApiKeyStatus[]>('/api/v1/me/api-keys', fetcher)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const configured = new Set((keys ?? []).filter((k) => k.configured).map((k) => k.provider))
  const current = PROVIDERS.find((p) => p.value === integrations?.tiktok_provider) ?? PROVIDERS[2]
  const missingKey = Boolean(current.keyProvider && !configured.has(current.keyProvider))

  const changeProvider = async (provider: TikTokProvider) => {
    setError(null)
    setBusy(true)
    try {
      await mutate(await setTikTokProvider(channelId, provider), { revalidate: false })
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const connect = async () => {
    setError(null)
    setBusy(true)
    try {
      const { redirect_url } = await connectTikTok(channelId)
      window.location.href = redirect_url
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  if (!integrations) return null

  return (
    <Box sx={{ maxWidth: 640 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>Publication TikTok</Typography>
      {!integrations.tiktok_enabled && (
        <Alert severity="info" sx={{ mb: 2 }}>TikTok est désactivé pour cette chaîne.</Alert>
      )}
      <TextField
        select
        fullWidth
        label="Fournisseur TikTok"
        value={current.value}
        disabled={busy}
        helperText={current.help}
        sx={{ mb: 2 }}
        onChange={(e) => changeProvider(e.target.value as TikTokProvider)}
      >
        {PROVIDERS.map((p) => (
          <MenuItem key={p.value} value={p.value}>
            {p.label}
            {p.keyProvider && !configured.has(p.keyProvider) ? ' — clé API manquante' : ''}
          </MenuItem>
        ))}
      </TextField>

      {missingKey && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Ajoutez d’abord votre clé {current.label} dans{' '}
          <Link href="/account/api-keys">Compte → Clés API</Link>.
        </Alert>
      )}

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 2, mb: 2 }}>
        <Chip
          label={
            integrations.tiktok_connected
              ? `TikTok connecté${integrations.tiktok_username ? ` (@${integrations.tiktok_username})` : ''}`
              : 'TikTok non connecté'
          }
          color={integrations.tiktok_connected ? 'success' : 'default'}
        />
        <Button
          variant="outlined"
          disabled={busy || missingKey || !integrations.tiktok_enabled}
          onClick={connect}
        >
          {integrations.tiktok_connected ? 'Reconnecter TikTok' : 'Connecter TikTok'}
        </Button>
      </Box>

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
    </Box>
  )
}
