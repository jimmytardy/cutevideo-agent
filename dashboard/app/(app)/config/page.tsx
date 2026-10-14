'use client'

import { useState, useEffect } from 'react'
import useSWR from 'swr'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import AdminGuard from '@/components/AdminGuard'
import { PageContainer, PageHeader, LoadingState } from '@/components/layout'
import { fetcher, saveAgentConfig } from '@/lib/api'

export default function ConfigPage() {
  const { data, isLoading, mutate } = useSWR('/api/v1/config/agent', fetcher)
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (data) setValue(JSON.stringify(data, null, 2))
  }, [data])

  const handleSave = async () => {
    setSaving(true)
    setError(null)
    let parsed: unknown
    try {
      parsed = JSON.parse(value)
    } catch {
      setError('JSON invalide — vérifiez la syntaxe.')
      setSaving(false)
      return
    }
    try {
      await saveAgentConfig(parsed)
      await mutate()
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError(`Échec de la sauvegarde : ${e instanceof Error ? e.message : String(e)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <AdminGuard>
      <PageContainer maxWidth="md">
        <PageHeader
          title="Configuration agents"
          description="Éditez la configuration globale des agents (réservé aux administrateurs)."
        />
        {saved && <Alert severity="success" sx={{ mb: 2 }}>Configuration sauvegardée</Alert>}
        {error && <Alert severity="error" sx={{ mb: 2 }}>{error}</Alert>}
        <Card>
          <CardContent>
            {isLoading ? (
              <LoadingState variant="table" count={4} />
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
      </PageContainer>
    </AdminGuard>
  )
}
