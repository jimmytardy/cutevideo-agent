'use client'

import { useState } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardActions from '@mui/material/CardActions'
import Chip from '@mui/material/Chip'
import Alert from '@mui/material/Alert'
import Dialog from '@mui/material/Dialog'
import DialogTitle from '@mui/material/DialogTitle'
import DialogContent from '@mui/material/DialogContent'
import DialogActions from '@mui/material/DialogActions'
import TextField from '@mui/material/TextField'
import MenuItem from '@mui/material/MenuItem'
import AddIcon from '@mui/icons-material/Add'
import LinkIcon from '@mui/icons-material/Link'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import SettingsIcon from '@mui/icons-material/Settings'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import {
  PageContainer,
  PageHeader,
  EmptyState,
  LoadingState,
  ErrorState,
} from '@/components/layout'
import {
  connectTikTok,
  createChannel,
  fetchChannelIntegrations,
  fetchChannels,
  fetchRunwayStatus,
  type Channel,
} from '@/lib/api'

const THEME_CATEGORIES = ['histoire', 'science', 'nature', 'art', 'default']

function ChannelCard({ channel, onRefresh }: { channel: Channel; onRefresh: () => void }) {
  const { data: integrations, mutate: mutateIntegrations } = useSWR(
    `/api/v1/channels/${channel.id}/integrations`,
    () => fetchChannelIntegrations(channel.id),
  )

  const runwayEnabled = Boolean((channel.config as Record<string, unknown> | null)?.runway && ((channel.config as Record<string, Record<string, unknown>>).runway?.enabled))
  const { data: runwayStatus } = useSWR(
    runwayEnabled ? `/api/v1/channels/${channel.id}/runway-status` : null,
    () => fetchRunwayStatus(channel.id),
    { refreshInterval: 60000 },
  )

  const handleConnectTikTok = async () => {
    const { redirect_url } = await connectTikTok(channel.id)
    window.open(redirect_url, '_blank', 'noopener,noreferrer')
    setTimeout(() => mutateIntegrations(), 5000)
    onRefresh()
  }

  return (
    <Card>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
          <Typography variant="h6">{channel.name}</Typography>
          <Box sx={{ display: 'flex', gap: 0.5 }}>
            {channel.onboarding_step && channel.onboarding_step !== 'complete' && (
              <Chip label="Config en cours" size="small" color="warning" />
            )}
            <Chip label={channel.theme_category} size="small" color="primary" variant="outlined" />
          </Box>
        </Box>
        <Typography variant="body2" color="text.secondary">
          Slug : {channel.slug}
        </Typography>
        {channel.niche_prompt && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
            {channel.niche_prompt}
          </Typography>
        )}
        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mt: 2 }}>
          <Chip
            label={integrations?.tiktok_connected ? 'TikTok connecté' : 'TikTok non connecté'}
            size="small"
            color={integrations?.tiktok_connected ? 'success' : 'default'}
          />
          {integrations?.youtube_configured && (
            <Chip label="YouTube OK" size="small" color="info" variant="outlined" />
          )}
          {integrations?.instagram_configured && (
            <Chip label="Instagram OK" size="small" color="info" variant="outlined" />
          )}
          {runwayEnabled && (
            <Chip
              label={runwayStatus?.credit_error ? 'Runway — crédits épuisés' : 'Runway actif'}
              size="small"
              color={runwayStatus?.credit_error ? 'error' : 'secondary'}
              variant={runwayStatus?.credit_error ? 'filled' : 'outlined'}
            />
          )}
        </Box>
        {runwayStatus?.credit_error && (
          <Alert severity="error" sx={{ mt: 2 }} variant="outlined">
            Crédits Runway insuffisants — les clips vidéo IA sont suspendus.
            Rechargez sur <strong>app.runwayml.com</strong>.
          </Alert>
        )}
      </CardContent>
      <CardActions>
        <Button
          size="small"
          component={Link}
          href={`/channels/${channel.id}/settings`}
          startIcon={<SettingsIcon />}
        >
          Paramètres
        </Button>
        {channel.onboarding_step && channel.onboarding_step !== 'complete' && (
          <Button
            size="small"
            component={Link}
            href={`/channels/${channel.id}/setup`}
            startIcon={<SettingsIcon />}
          >
            Reprendre l&apos;onboarding
          </Button>
        )}
        {channel.tiktok_enabled && !integrations?.tiktok_connected && (
          <Button size="small" startIcon={<LinkIcon />} onClick={handleConnectTikTok}>
            Connecter TikTok
          </Button>
        )}
      </CardActions>
    </Card>
  )
}

export default function ChannelsPage() {
  const router = useRouter()
  const { data: channels, error, isLoading, mutate } = useSWR<Channel[]>(
    '/api/v1/channels',
    () => fetchChannels(),
  )
  const [open, setOpen] = useState(false)
  const [slug, setSlug] = useState('')
  const [name, setName] = useState('')
  const [themeCategory, setThemeCategory] = useState('histoire')
  const [nichePrompt, setNichePrompt] = useState('')
  const [creating, setCreating] = useState(false)

  const handleCreate = async () => {
    if (!slug.trim() || !name.trim()) return
    setCreating(true)
    try {
      await createChannel({
        slug: slug.trim(),
        name: name.trim(),
        theme_category: themeCategory,
        niche_prompt: nichePrompt.trim() || undefined,
      })
      await mutate()
      setOpen(false)
      setSlug('')
      setName('')
      setNichePrompt('')
    } finally {
      setCreating(false)
    }
  }

  return (
    <PageContainer>
      <PageHeader
        title="Chaînes"
        description="Gérez vos chaînes YouTube, TikTok et Instagram."
        actions={
          <>
            <Button variant="contained" startIcon={<AutoAwesomeIcon />} onClick={() => router.push('/channels/new')}>
              Créer une chaîne guidée
            </Button>
            <Button variant="outlined" startIcon={<AddIcon />} onClick={() => setOpen(true)}>
              Création rapide
            </Button>
          </>
        }
      />

      {isLoading && <LoadingState count={4} />}
      {error && <ErrorState message="Impossible de charger les chaînes" onRetry={() => mutate()} />}
      {!isLoading && !error && channels?.length === 0 && (
        <EmptyState
          title="Aucune chaîne"
          description="Créez votre première chaîne pour commencer à produire des vidéos."
          actionLabel="Créer une chaîne"
          actionHref="/channels/new"
        />
      )}

      {channels && channels.length > 0 && (
        <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {channels.map((c) => (
            <ChannelCard key={c.id} channel={c} onRefresh={mutate} />
          ))}
        </Box>
      )}

      <Dialog open={open} onClose={() => setOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Nouvelle chaîne</DialogTitle>
        <DialogContent sx={{ pt: 2, display: 'flex', flexDirection: 'column', gap: 2 }}>
          <TextField
            label="Slug"
            placeholder="science"
            fullWidth
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
          />
          <TextField
            label="Nom"
            placeholder="Science & Découvertes"
            fullWidth
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <TextField
            select
            label="Catégorie thématique"
            fullWidth
            value={themeCategory}
            onChange={(e) => setThemeCategory(e.target.value)}
          >
            {THEME_CATEGORIES.map((c) => (
              <MenuItem key={c} value={c}>
                {c}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="Contexte éditorial"
            placeholder="Style Kurzgesagt en français..."
            fullWidth
            multiline
            rows={2}
            value={nichePrompt}
            onChange={(e) => setNichePrompt(e.target.value)}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setOpen(false)}>Annuler</Button>
          <Button
            variant="contained"
            onClick={handleCreate}
            disabled={!slug.trim() || !name.trim() || creating}
          >
            Créer
          </Button>
        </DialogActions>
      </Dialog>
    </PageContainer>
  )
}
