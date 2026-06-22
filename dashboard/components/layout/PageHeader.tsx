'use client'

import Box from '@mui/material/Box'
import Breadcrumbs from '@mui/material/Breadcrumbs'
import Link from '@mui/material/Link'
import Typography from '@mui/material/Typography'
import NextLink from 'next/link'

export interface BreadcrumbItem {
  label: string
  href?: string
}

interface PageHeaderProps {
  title: string
  description?: string
  actions?: React.ReactNode
  breadcrumbs?: BreadcrumbItem[]
}

export default function PageHeader({ title, description, actions, breadcrumbs }: PageHeaderProps) {
  return (
    <Box
      sx={{
        mb: { xs: 3, md: 4 },
        display: 'flex',
        flexDirection: { xs: 'column', sm: 'row' },
        alignItems: { xs: 'flex-start', sm: 'flex-start' },
        justifyContent: 'space-between',
        gap: 2,
      }}
    >
      <Box sx={{ minWidth: 0 }}>
        {breadcrumbs && breadcrumbs.length > 0 && (
          <Breadcrumbs sx={{ mb: 1 }} aria-label="fil d'Ariane">
            {breadcrumbs.map((item, index) => {
              const isLast = index === breadcrumbs.length - 1
              if (isLast || !item.href) {
                return (
                  <Typography key={item.label} variant="body2" color="text.secondary">
                    {item.label}
                  </Typography>
                )
              }
              return (
                <Link
                  key={item.label}
                  component={NextLink}
                  href={item.href}
                  underline="hover"
                  color="text.secondary"
                  variant="body2"
                >
                  {item.label}
                </Link>
              )
            })}
          </Breadcrumbs>
        )}
        <Typography variant="h4" component="h1" gutterBottom={Boolean(description)}>
          {title}
        </Typography>
        {description && (
          <Typography variant="body1" color="text.secondary" sx={{ maxWidth: 720 }}>
            {description}
          </Typography>
        )}
      </Box>
      {actions && (
        <Box sx={{ display: 'flex', gap: 1, flexShrink: 0, flexWrap: 'wrap' }}>{actions}</Box>
      )}
    </Box>
  )
}
