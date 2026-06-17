'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Alert from '@mui/material/Alert'
import Chip from '@mui/material/Chip'
import { BarChart } from '@mui/x-charts/BarChart'
import AppShell from '@/components/AppShell'
import { fetcher, type Project } from '@/lib/api'

interface Publication {
  id: string
  platform: string
  title: string
  platform_url: string
  status: string
  published_at: string
}

export default function AnalyticsPage() {
  const { data: projects } = useSWR<Project[]>('/api/v1/projects', fetcher, { refreshInterval: 10000 })
  const latestProject = projects?.[0]

  const { data: publications } = useSWR<Publication[]>(
    latestProject ? `/api/v1/analytics/publications/${latestProject.id}` : null,
    fetcher,
    { refreshInterval: 10000 },
  )

  const byPlatform = ['youtube', 'tiktok', 'instagram'].map((p) => ({
    platform: p,
    count: publications?.filter((pub) => pub.platform === p).length ?? 0,
  }))

  return (
    <AppShell>
      <Box sx={{ maxWidth: 1100, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 3 }}>Analytics</Typography>

        {!publications?.length ? (
          <Alert severity="info">Aucune publication disponible pour l&apos;instant.</Alert>
        ) : (
          <>
            <Card sx={{ mb: 3 }}>
              <CardContent>
                <Typography variant="h6" sx={{ mb: 2 }}>Publications par plateforme</Typography>
                <BarChart
                  xAxis={[{ data: byPlatform.map((b) => b.platform), scaleType: 'band' }]}
                  series={[{ data: byPlatform.map((b) => b.count), label: 'Publications' }]}
                  height={250}
                />
              </CardContent>
            </Card>

            <Typography variant="h6" sx={{ mb: 2 }}>Dernières publications</Typography>
            <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {publications.map((pub) => (
                <Card key={pub.id}>
                  <CardContent>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                      <Chip label={pub.platform} size="small" color="primary" />
                      <Chip label={pub.status} size="small" />
                    </Box>
                    <Typography variant="body2" fontWeight={600} noWrap>
                      {pub.title}
                    </Typography>
                    {pub.published_at && (
                      <Typography variant="caption" color="text.secondary">
                        {new Date(pub.published_at).toLocaleDateString('fr-FR')}
                      </Typography>
                    )}
                  </CardContent>
                </Card>
              ))}
            </Box>
          </>
        )}
      </Box>
    </AppShell>
  )
}
