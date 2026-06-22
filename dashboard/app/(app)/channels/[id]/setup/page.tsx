'use client'

import { useParams, useRouter } from 'next/navigation'
import useSWR from 'swr'
import Button from '@mui/material/Button'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import Stack from '@mui/material/Stack'
import { PageContainer, PageHeader, LoadingState } from '@/components/layout'
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

  if (isLoading) return <LoadingState variant="page" />

  if (error || !channel) {
    return (
      <PageContainer maxWidth="sm">
        <Alert severity="error">Chaîne introuvable</Alert>
      </PageContainer>
    )
  }

  const step = channel.onboarding_step || 'complete'

  if (step === 'complete') {
    return (
      <PageContainer maxWidth="sm">
        <PageHeader title="Onboarding terminé" />
        <Alert severity="success">L&apos;onboarding de cette chaîne est terminé.</Alert>
        <Button sx={{ mt: 2 }} onClick={() => router.push('/channels')}>
          Retour aux chaînes
        </Button>
      </PageContainer>
    )
  }

  return (
    <PageContainer maxWidth="sm">
      <PageHeader
        title={`Reprendre l'onboarding — ${channel.name}`}
        description="Finalisez la configuration YouTube, TikTok et Instagram."
        breadcrumbs={[
          { label: 'Chaînes', href: '/channels' },
          { label: channel.name, href: `/channels/${channelId}/settings` },
          { label: 'Onboarding' },
        ]}
      />
      <Chip label={`Étape : ${STEP_LABELS[step] || step}`} color="warning" sx={{ mb: 2 }} />
      <Alert severity="info" sx={{ mb: 3 }}>
        Cette chaîne est en cours de configuration. Reprenez l&apos;assistant guidé pour finaliser les
        intégrations.
      </Alert>
      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
        <Button variant="contained" onClick={() => router.push('/channels/new')}>
          Ouvrir l&apos;assistant
        </Button>
        <Button variant="outlined" onClick={() => router.push('/channels')}>
          Retour
        </Button>
      </Stack>
    </PageContainer>
  )
}
