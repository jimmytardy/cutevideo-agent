'use client'

import Box from '@mui/material/Box'
import Container from '@mui/material/Container'

type MaxWidth = 'sm' | 'md' | 'lg' | 'xl' | false

interface PageContainerProps {
  children: React.ReactNode
  maxWidth?: MaxWidth
}

export default function PageContainer({ children, maxWidth = 'lg' }: PageContainerProps) {
  return (
    <Container maxWidth={maxWidth} disableGutters sx={{ px: { xs: 0, sm: 1 } }}>
      <Box sx={{ py: { xs: 0, sm: 0.5 } }}>{children}</Box>
    </Container>
  )
}
