import useSWR from 'swr'

import { API_BASE, fetcher, type AuthUser } from '@/lib/api'

/** Utilisateur connecté (clé SWR partagée : une seule requête pour toute l'interface). */
export function useMe() {
  return useSWR<AuthUser>(`${API_BASE}/auth/me`, fetcher)
}
