'use client'

import Alert from '@mui/material/Alert'
import Button from '@mui/material/Button'

interface ErrorStateProps {
  message?: string
  onRetry?: () => void
}

export default function ErrorState({
  message = 'Une erreur est survenue lors du chargement.',
  onRetry,
}: ErrorStateProps) {
  return (
    <Alert
      severity="error"
      action={
        onRetry ? (
          <Button color="inherit" size="small" onClick={onRetry}>
            Réessayer
          </Button>
        ) : undefined
      }
    >
      {message}
    </Alert>
  )
}
