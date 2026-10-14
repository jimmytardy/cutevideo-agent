'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'
import CircularProgress from '@mui/material/CircularProgress'

import { PageContainer, PageHeader } from '@/components/layout'
import { finishTikTokConnect } from '@/lib/api'

/** Retour OAuth TikTok (Post for Me / Zernio) : finalise la connexion avec le jeton de session. */
export default function TikTokConnectedPage({ params }: { params: { id: string } }) {
  const router = useRouter()
  const search = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  const [username, setUsername] = useState<string | null>(null)
  const done = useRef(false)

  useEffect(() => {
    if (done.current) return
    done.current = true
    const state = search.get('state')
    if (!state) {
      setError('Paramètre « state » manquant dans le retour TikTok.')
      return
    }
    const extra: Record<string, string> = {}
    search.forEach((value, key) => {
      if (key !== 'state') extra[key] = value
    })
    finishTikTokConnect(params.id, state, extra)
      .then((res) => {
        setUsername(res.tiktok_username ?? '')
        setTimeout(() => router.replace(`/channels/${params.id}/settings`), 1500)
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [params.id, router, search])

  return (
    <PageContainer>
      <PageHeader title="Connexion TikTok" />
      {error ? (
        <>
          <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>
          <Button variant="outlined" onClick={() => router.replace(`/channels/${params.id}/settings`)}>
            Retour à la chaîne
          </Button>
        </>
      ) : username !== null ? (
        <Alert severity="success">TikTok connecté{username ? ` (@${username})` : ''}. Redirection…</Alert>
      ) : (
        <CircularProgress />
      )}
    </PageContainer>
  )
}
