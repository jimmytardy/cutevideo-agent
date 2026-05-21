'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import AppShell from '@/components/AppShell'
import { fetcher } from '@/lib/api'

export default function ConfigPage() {
  const { data, isLoading, mutate } = useSWR('/api/v1/config/agent', fetcher)
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    if (data) setValue(JSON.stringify(data, null, 2))
  }, [data])

  const handleSave = async () => {
    setSaving(true)
    try {
      const parsed = JSON.parse(value)
      await fetch('/api/v1/config/agent', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(parsed),
      })
      await mutate()
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch {
      alert('JSON invalide')
    } finally {
      setSaving(false)
    }
  }

  return (
    <AppShell>
      <Box sx={{ maxWidth: 800, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 3 }}>Configuration agents</Typography>
        {saved && <Alert severity="success" sx={{ mb: 2 }}>Configuration sauvegardée</Alert>}
        <Card>
          <CardContent>
            {isLoading ? (
              <CircularProgress />
            ) : (
              <>
                <TextField
                  multiline
                  fullWidth
                  rows={20}
                  value={value}
                  onChange={(e) => setValue(e.target.value)}
                  InputProps={{ sx: { fontFamily: 'monospace', fontSize: 13 } }}
                  sx={{ mb: 2 }}
                />
                <Button
                  variant="contained"
                  onClick={handleSave}
                  disabled={saving}
                  startIcon={saving ? <CircularProgress size={16} /> : undefined}
                >
                  Sauvegarder
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </Box>
    </AppShell>
  )
}
