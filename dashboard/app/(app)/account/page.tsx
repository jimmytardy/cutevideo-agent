'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Grid from '@mui/material/Grid'
import { PageContainer, PageHeader, StatCard } from '@/components/layout'
import { fetcher, type AuthUser, type SubscriptionInfo } from '@/lib/api'

const BASE = '/api/v1'

export default function AccountPage() {
  const { data: sub } = useSWR<SubscriptionInfo>(`${BASE}/me/subscription`, fetcher)
  const { data: me } = useSWR<AuthUser>(`${BASE}/auth/me`, fetcher)

  const storageMb = Math.round(Number(sub?.usage?.storage_bytes ?? 0) / 1024 / 1024)

  return (
    <PageContainer maxWidth="md">
      <PageHeader
        title="Mon compte"
        description={me ? (me.display_name || me.email) : undefined}
      />

      <Grid container spacing={3}>
        <Grid item xs={12} sm={6}>
          <StatCard label="Plan actuel" value={sub?.plan_name ?? '—'} hint={me?.plan_slug} />
        </Grid>
        <Grid item xs={12} sm={6}>
          <StatCard
            label="Chaînes"
            value={`${String(sub?.usage?.channels ?? 0)} / ${String(sub?.limits?.max_channels ?? '?')}`}
          />
        </Grid>
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <Typography variant="h6">Abonnement</Typography>
                {sub && <Chip label={sub.plan_name} color="primary" size="small" />}
              </Box>
              {me && (
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  {me.email}
                </Typography>
              )}
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Stockage utilisé : {storageMb} Mo
              </Typography>
              {sub?.is_unlimited && (
                <Chip label="Plan illimité" color="success" size="small" sx={{ mt: 1 }} />
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </PageContainer>
  )
}
