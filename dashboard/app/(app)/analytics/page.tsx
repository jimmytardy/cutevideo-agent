'use client'

import useSWR from 'swr'
import Box from '@mui/material/Box'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Typography from '@mui/material/Typography'
import { BarChart } from '@mui/x-charts/BarChart'
import { useTheme } from '@mui/material/styles'
import { PageContainer, PageHeader, PageSection, EmptyState } from '@/components/layout'
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
  const theme = useTheme()
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

  const chartColor = theme.palette.primary.main

  return (
    <PageContainer>
      <PageHeader
        title="Analytics"
        description="Suivez vos publications sur YouTube, TikTok et Instagram."
      />

      {!publications?.length ? (
        <EmptyState
          title="Aucune publication"
          description="Les statistiques apparaîtront une fois vos vidéos publiées sur les plateformes."
        />
      ) : (
        <>
          <PageSection title="Publications par plateforme">
            <Card>
              <CardContent>
                <BarChart
                  xAxis={[{ data: byPlatform.map((b) => b.platform), scaleType: 'band' }]}
                  series={[{ data: byPlatform.map((b) => b.count), label: 'Publications', color: chartColor }]}
                  height={280}
                  margin={{ top: 20, bottom: 30, left: 40, right: 20 }}
                />
              </CardContent>
            </Card>
          </PageSection>

          <PageSection title="Dernières publications">
            <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))' }}>
              {publications.map((pub) => (
                <Card key={pub.id}>
                  <CardContent>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 1 }}>
                      <Chip label={pub.platform} size="small" color="primary" />
                      <Chip label={pub.status} size="small" variant="outlined" />
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
          </PageSection>
        </>
      )}
    </PageContainer>
  )
}
