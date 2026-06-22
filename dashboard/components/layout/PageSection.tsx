'use client'

import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'

interface PageSectionProps {
  title?: string
  description?: string
  actions?: React.ReactNode
  children: React.ReactNode
}

export default function PageSection({ title, description, actions, children }: PageSectionProps) {
  return (
    <Box sx={{ mb: 4 }}>
      {(title || actions) && (
        <Box
          sx={{
            display: 'flex',
            alignItems: 'flex-start',
            justifyContent: 'space-between',
            gap: 2,
            mb: 2,
          }}
        >
          <Box>
            {title && (
              <Typography variant="h6" component="h2">
                {title}
              </Typography>
            )}
            {description && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                {description}
              </Typography>
            )}
          </Box>
          {actions}
        </Box>
      )}
      {children}
    </Box>
  )
}
