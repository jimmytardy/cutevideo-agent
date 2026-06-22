'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CircularProgress from '@mui/material/CircularProgress'
import Link from '@mui/material/Link'
import Typography from '@mui/material/Typography'
import VideoLibraryOutlinedIcon from '@mui/icons-material/VideoLibraryOutlined'
import NextLink from 'next/link'
import { ThemeToggle } from '@/components/layout'
import { getGoogleLoginUrl, setAuthToken } from '@/lib/api'

function LoginPageContent() {
  const router = useRouter()
  const searchParams = useSearchParams()

  useEffect(() => {
    const token = searchParams.get('token')
    if (token) {
      setAuthToken(token)
      router.replace('/')
    }
  }, [searchParams, router])

  const handleGoogleLogin = async () => {
    const { authorization_url } = await getGoogleLoginUrl()
    window.location.href = authorization_url
  }

  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', flexDirection: { xs: 'column', md: 'row' } }}>
      <Box
        sx={{
          flex: 1,
          display: { xs: 'none', md: 'flex' },
          flexDirection: 'column',
          justifyContent: 'center',
          p: 6,
          bgcolor: 'primary.main',
          color: 'primary.contrastText',
        }}
      >
        <VideoLibraryOutlinedIcon sx={{ fontSize: 56, mb: 3, opacity: 0.9 }} />
        <Typography variant="h3" fontWeight={700} gutterBottom>
          CuteVideo Agent
        </Typography>
        <Typography variant="h6" sx={{ opacity: 0.9, maxWidth: 420, fontWeight: 400 }}>
          Pipeline IA multi-agents pour créer des vidéos éducatives longues et des shorts automatiquement.
        </Typography>
      </Box>

      <Box
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          p: { xs: 3, sm: 6 },
          bgcolor: 'background.default',
          position: 'relative',
        }}
      >
        <Box sx={{ position: 'absolute', top: 16, right: 16 }}>
          <ThemeToggle />
        </Box>

        <Card sx={{ width: '100%', maxWidth: 420, boxShadow: { xs: 0, sm: 2 } }}>
          <CardContent sx={{ p: { xs: 3, sm: 4 } }}>
            <Box sx={{ display: { md: 'none' }, mb: 3, textAlign: 'center' }}>
              <Typography variant="h5" fontWeight={700} color="primary.main">
                CuteVideo Agent
              </Typography>
            </Box>
            <Typography variant="h5" fontWeight={700} gutterBottom>
              Connexion
            </Typography>
            <Typography color="text.secondary" sx={{ mb: 3 }}>
              Connectez-vous avec Google pour accéder à vos chaînes, projets et paramètres.
            </Typography>
            <Button variant="contained" size="large" fullWidth onClick={handleGoogleLogin}>
              Continuer avec Google
            </Button>
            <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', justifyContent: 'center', mt: 3 }}>
              <Link component={NextLink} href="/terms" variant="body2" color="text.secondary">
                Conditions d&apos;utilisation
              </Link>
              <Link component={NextLink} href="/privacy" variant="body2" color="text.secondary">
                Confidentialité
              </Link>
            </Box>
          </CardContent>
        </Card>
      </Box>
    </Box>
  )
}

function LoginPageFallback() {
  return (
    <Box sx={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <CircularProgress />
    </Box>
  )
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginPageFallback />}>
      <LoginPageContent />
    </Suspense>
  )
}
