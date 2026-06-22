'use client'

import Box from '@mui/material/Box'
import Grid from '@mui/material/Grid'
import Skeleton from '@mui/material/Skeleton'

interface LoadingStateProps {
  variant?: 'cards' | 'table' | 'page'
  count?: number
}

export default function LoadingState({ variant = 'cards', count = 3 }: LoadingStateProps) {
  if (variant === 'page') {
    return (
      <Box>
        <Skeleton variant="text" width="40%" height={40} sx={{ mb: 1 }} />
        <Skeleton variant="text" width="60%" height={24} sx={{ mb: 4 }} />
        <Grid container spacing={3}>
          {[0, 1, 2].map((i) => (
            <Grid item xs={12} md={4} key={i}>
              <Skeleton variant="rounded" height={140} />
            </Grid>
          ))}
        </Grid>
      </Box>
    )
  }

  if (variant === 'table') {
    return (
      <Box>
        {Array.from({ length: count }).map((_, i) => (
          <Skeleton key={i} variant="rounded" height={48} sx={{ mb: 1 }} />
        ))}
      </Box>
    )
  }

  return (
    <Box sx={{ display: 'grid', gap: 2, gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))' }}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} variant="rounded" height={180} />
      ))}
    </Box>
  )
}
