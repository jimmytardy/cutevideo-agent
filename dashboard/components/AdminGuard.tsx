'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Box from '@mui/material/Box'
import CircularProgress from '@mui/material/CircularProgress'
import useSWR from 'swr'
import { fetcher, type AuthUser } from '@/lib/api'

const BASE = '/api/v1'

export default function AdminGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const { data: me, isLoading } = useSWR<AuthUser>(`${BASE}/auth/me`, fetcher)

  useEffect(() => {
    if (!isLoading && me && !me.is_admin) {
      router.replace('/')
    }
  }, [isLoading, me, router])

  if (isLoading || !me) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', mt: 8 }}>
        <CircularProgress />
      </Box>
    )
  }

  if (!me.is_admin) {
    return null
  }

  return <>{children}</>
}
