import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Grid from '@mui/material/Grid'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Button from '@mui/material/Button'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import BarChartIcon from '@mui/icons-material/BarChart'
import Link from 'next/link'
import AppShell from '@/components/AppShell'

const FEATURES = [
  {
    icon: <VideoLibraryIcon sx={{ fontSize: 40, color: 'primary.main' }} />,
    title: 'Projets Vidéo',
    desc: 'Créez et gérez vos projets de vidéos éducatives longues et shorts.',
    href: '/projects',
    cta: 'Voir les projets',
  },
  {
    icon: <SmartToyIcon sx={{ fontSize: 40, color: 'secondary.main' }} />,
    title: 'Agents IA',
    desc: 'Monitorez le pipeline en temps réel : 8 agents spécialisés en action.',
    href: '/agents',
    cta: 'Surveiller les agents',
  },
  {
    icon: <BarChartIcon sx={{ fontSize: 40, color: 'success.main' }} />,
    title: 'Analytics',
    desc: 'Suivez les performances de vos publications sur toutes les plateformes.',
    href: '/analytics',
    cta: 'Voir les analytics',
  },
]

export default function HomePage() {
  return (
    <AppShell>
      <Box sx={{ py: 6, px: 2, maxWidth: 1100, mx: 'auto' }}>
        <Typography variant="h4" gutterBottom fontWeight={700}>
          CuteVideo Agent
        </Typography>
        <Typography variant="body1" color="text.secondary" sx={{ mb: 5 }}>
          Pipeline IA multi-agents — génération automatique de vidéos éducatives longues + shorts
        </Typography>

        <Grid container spacing={3}>
          {FEATURES.map((f) => (
            <Grid item xs={12} md={4} key={f.title}>
              <Card sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                <CardContent sx={{ flex: 1 }}>
                  <Box sx={{ mb: 2 }}>{f.icon}</Box>
                  <Typography variant="h6" gutterBottom>
                    {f.title}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {f.desc}
                  </Typography>
                </CardContent>
                <Box sx={{ px: 2, pb: 2 }}>
                  <Button component={Link} href={f.href} variant="contained" fullWidth>
                    {f.cta}
                  </Button>
                </Box>
              </Card>
            </Grid>
          ))}
        </Grid>
      </Box>
    </AppShell>
  )
}
