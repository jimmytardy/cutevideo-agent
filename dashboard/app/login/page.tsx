'use client'

import { Suspense, useEffect } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'
import Typography from '@mui/material/Typography'
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
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexDirection: 'column',
        gap: 3,
        p: 3,
      }}
    >
      <Typography variant="h4" fontWeight={700}>
        CuteVideo Agent
      </Typography>
      <Typography color="text.secondary" textAlign="center" maxWidth={420}>
        Connectez-vous avec Google pour accéder à vos chaînes, projets et paramètres.
      </Typography>
      <Button variant="contained" size="large" onClick={handleGoogleLogin}>
        Continuer avec Google
      </Button>
    </Box>
  )
}

function LoginPageFallback() {
  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
      }}
    >
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
