'use client'

import { useEffect, useState } from 'react'
import { getMediaToken, MEDIA_TOKEN_REFRESH_MARGIN_MS } from '@/lib/api'

const RETRY_MS = 10_000

/**
 * Jeton média de la page (voir `getMediaToken`), renouvelé peu avant son expiration pour que les médias qui
 * apparaissent plus tard (fin de création, nouvelle itération) reçoivent un jeton valide. Le renouvellement
 * change le `src` des balises : une vidéo en lecture à cet instant précis repart du début (toutes les ~14 min).
 */
export function useMediaToken(): string | null {
  const [token, setToken] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () => {
      getMediaToken().then(
        (fresh) => {
          if (cancelled) return
          setToken(fresh.token)
          timer = setTimeout(load, Math.max(5_000, fresh.expiresAt - Date.now() - MEDIA_TOKEN_REFRESH_MARGIN_MS / 2))
        },
        () => {
          // Réseau ou API indisponible : on réessaie, les médias restent vides en attendant.
          if (!cancelled) timer = setTimeout(load, RETRY_MS)
        },
      )
    }
    load()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [])
  return token
}
