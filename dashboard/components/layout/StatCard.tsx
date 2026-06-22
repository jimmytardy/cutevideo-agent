'use client'

import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Chip from '@mui/material/Chip'
import Typography from '@mui/material/Typography'
import Box from '@mui/material/Box'

interface StatCardProps {
  label: string
  value: string | number
  hint?: string
  trend?: { label: string; color?: 'success' | 'error' | 'warning' | 'default' }
  icon?: React.ReactNode
}

export default function StatCard({ label, value, hint, trend, icon }: StatCardProps) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', mb: 1 }}>
          <Typography variant="body2" color="text.secondary" fontWeight={600}>
            {label}
          </Typography>
          {icon && <Box sx={{ color: 'primary.main', opacity: 0.8 }}>{icon}</Box>}
        </Box>
        <Typography variant="h4" component="p" sx={{ mb: 0.5 }}>
          {value}
        </Typography>
        {hint && (
          <Typography variant="caption" color="text.secondary" display="block">
            {hint}
          </Typography>
        )}
        {trend && (
          <Chip size="small" label={trend.label} color={trend.color ?? 'default'} sx={{ mt: 1 }} />
        )}
      </CardContent>
    </Card>
  )
}
