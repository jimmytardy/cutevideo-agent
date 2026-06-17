'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import AppShell from '@/components/AppShell'
import AuthGuard from '@/components/AuthGuard'
import { fetcher, type AuthUser, type SubscriptionInfo } from '@/lib/api'

const BASE = '/api/v1'

export default function AccountPage() {
  const { data: sub } = useSWR<SubscriptionInfo>(`${BASE}/me/subscription`, fetcher)
  const { data: me } = useSWR<AuthUser>(`${BASE}/auth/me`, fetcher)

  return (
    <AuthGuard>
      <AppShell>
        <Typography variant="h5" fontWeight={700} gutterBottom>
          Mon compte
        </Typography>
        {me && (
          <Typography color="text.secondary" gutterBottom>
            {me.display_name || me.email}
          </Typography>
        )}
        {sub && (
          <Card sx={{ mt: 2, maxWidth: 560 }}>
            <CardContent>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <Typography variant="h6">Abonnement</Typography>
                <Chip label={sub.plan_name} color="primary" size="small" />
              </Box>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Chaînes : {String(sub.usage?.channels ?? 0)} / {String(sub.limits?.max_channels ?? '?')}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                Stockage : {Math.round(Number(sub.usage?.storage_bytes ?? 0) / 1024 / 1024)} Mo utilisés
              </Typography>
            </CardContent>
          </Card>
        )}
      </AppShell>
    </AuthGuard>
  )
}
