'use client'

import { SWRConfig } from 'swr'
import { fetcher, swrOnErrorRetry } from '@/lib/api'

export default function SWRProvider({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig value={{ fetcher, onErrorRetry: swrOnErrorRetry }}>
      {children}
    </SWRConfig>
  )
}
