'use client'

import { useEffect, useState } from 'react'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'

const BROADCAST_CHANNEL = 'cutevideo_youtube_oauth'

export default function YoutubeOAuthDonePage() {
  const [message, setMessage] = useState<'loading' | 'success' | 'error'>('loading')
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const channelId = params.get('channel_id')
    const error = params.get('error')
    const ok = params.get('status') === 'ok' && !error

    const payload = {
      type: 'youtube_oauth',
      status: ok ? 'ok' : 'error',
      channelId: channelId ?? undefined,
      error: error ?? undefined,
    }

    try {
      const bc = new BroadcastChannel(BROADCAST_CHANNEL)
      bc.postMessage(payload)
      bc.close()
    } catch {
      // BroadcastChannel indisponible — fermer manuellement l'onglet.
    }

    if (window.opener && !window.opener.closed) {
      window.opener.postMessage(payload, window.location.origin)
    }

    if (ok) {
      setMessage('success')
      window.close()
      return
    }

    setErrorDetail(error)
    setMessage('error')
  }, [])

  if (message === 'loading') {
    return (
      <Box sx={{ p: 4, maxWidth: 420, mx: 'auto', textAlign: 'center' }}>
        <CircularProgress sx={{ mb: 2 }} />
        <Typography>Connexion YouTube réussie — retour à l&apos;assistant…</Typography>
      </Box>
    )
  }

  if (message === 'success') {
    return (
      <Box sx={{ p: 4, maxWidth: 420, mx: 'auto' }}>
        <Alert severity="success">YouTube connecté. Vous pouvez fermer cet onglet.</Alert>
      </Box>
    )
  }

  return (
    <Box sx={{ p: 4, maxWidth: 480, mx: 'auto' }}>
      <Alert severity="error">
        Connexion YouTube échouée{errorDetail ? ` : ${errorDetail}` : ''}. Fermez cet onglet et réessayez.
      </Alert>
    </Box>
  )
}
