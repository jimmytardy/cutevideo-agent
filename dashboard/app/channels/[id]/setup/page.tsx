'use client'

import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import Chip from '@mui/material/Chip'
import AppShell from '@/components/AppShell'
import { fetchChannel } from '@/lib/api'

const STEP_LABELS: Record<string, string> = {
  theme: 'Thème',
  brand: 'Identité / kit marque',
  youtube: 'YouTube',
  tiktok: 'TikTok',
  instagram: 'Instagram',
  complete: 'Terminé',
}

export default function ChannelSetupPage() {
  const params = useParams()
  const router = useRouter()
  const channelId = params.id as string

  const { data: channel, error, isLoading } = useSWR(
    channelId ? `/api/v1/channels/${channelId}` : null,
    () => fetchChannel(channelId),
  )

  if (isLoading) {
    return (
      <AppShell>
        <CircularProgress />
      </AppShell>
    )
  }

  if (error || !channel) {
    return (
      <AppShell>
        <Alert severity="error">Chaîne introuvable</Alert>
      </AppShell>
    )
  }

  const step = channel.onboarding_step || 'complete'

  if (step === 'complete') {
    return (
      <AppShell>
        <Alert severity="success">L&apos;onboarding de cette chaîne est terminé.</Alert>
        <Button sx={{ mt: 2 }} onClick={() => router.push('/channels')}>
          Retour aux chaînes
        </Button>
      </AppShell>
    )
  }

  return (
    <AppShell>
      <Box sx={{ maxWidth: 600, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 2 }}>
          Reprendre l&apos;onboarding — {channel.name}
        </Typography>
        <Chip label={`Étape : ${STEP_LABELS[step] || step}`} color="warning" sx={{ mb: 2 }} />
        <Alert severity="info" sx={{ mb: 2 }}>
          Cette chaîne est en cours de configuration. Reprenez l&apos;assistant guidé pour finaliser
          YouTube, TikTok et Instagram.
        </Alert>
        <Button variant="contained" onClick={() => router.push('/channels/new')}>
          Ouvrir l&apos;assistant (nouvelle session)
        </Button>
        <Button sx={{ mt: 2, ml: 2 }} onClick={() => router.push('/channels')}>
          Retour
        </Button>
      </Box>
    </AppShell>
  )
}
