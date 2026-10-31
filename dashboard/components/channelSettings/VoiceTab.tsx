'use client'

import Alert from '@mui/material/Alert'
import Box from '@mui/material/Box'
import MenuItem from '@mui/material/MenuItem'
import TextField from '@mui/material/TextField'
import Typography from '@mui/material/Typography'
import useSWR from 'swr'

import { fetcher } from '@/lib/api'
import type { ChannelSettingsForm, UpdateChannelForm } from '@/lib/channelSettingsForm'
import { TTS_ENGINES, voiceOptionsForEngine, type Voice } from '@/lib/channelSettingsOptions'

function VoiceField({ label, engine, value, onChange, azureVoices, geminiVoices }: {
  label: string
  engine: string
  value: string
  onChange: (voice: string) => void
  azureVoices?: Voice[]
  geminiVoices?: Voice[]
}) {
  if (engine === 'elevenlabs') {
    return <TextField fullWidth label={`${label} (Voice ID ElevenLabs)`} value={value} onChange={(e) => onChange(e.target.value)} />
  }
  const options = voiceOptionsForEngine(engine, azureVoices, geminiVoices)
  return (
    // Voix venue d'un autre moteur : absente de la liste, elle s'affiche vide plutôt que d'avertir MUI.
    <TextField select fullWidth label={label} value={options.some((v) => v.id === value) ? value : ''}
      onChange={(e) => onChange(e.target.value)}>
      {options.map((v) => <MenuItem key={v.id} value={v.id}>{v.label}</MenuItem>)}
    </TextField>
  )
}

interface Props {
  form: ChannelSettingsForm
  update: UpdateChannelForm
}

export default function VoiceTab({ form, update }: Props) {
  const { data: azureVoices } = useSWR<Voice[]>('/api/v1/config/tts/voices', fetcher)
  const { data: geminiVoices } = useSWR<Voice[]>('/api/v1/config/tts/gemini-voices', fetcher)
  const usesElevenLabs = form.tts_short_engine === 'elevenlabs' || form.tts_fallback_engine === 'elevenlabs'
  const { data: apiKeys } = useSWR<{ provider: string; configured: boolean }[]>(
    usesElevenLabs ? '/api/v1/me/api-keys' : null,
    fetcher,
  )
  const elevenLabsKeyMissing = apiKeys?.some((k) => k.provider === 'elevenlabs' && !k.configured)

  return (
    <>
      <Typography variant="h6" sx={{ mb: 1 }}>Voix &amp; synthèse (TTS)</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Moteur et voix de la narration des Shorts. Gemini nécessite votre clé Gemini (Compte → Clés API) ;
        Azure nécessite votre clé Azure Speech, ElevenLabs votre clé ElevenLabs. Edge TTS est gratuit (voix Azure HD remplacées par une voix edge).
      </Typography>

      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField select fullWidth label="Moteur" value={form.tts_short_engine}
          onChange={(e) => update({
            tts_short_engine: e.target.value,
            // La voix d'un autre moteur serait refusée ; un secours sur le moteur principal ne servirait à rien.
            ...(e.target.value !== form.tts_short_engine ? { tts_short_voice: '' } : {}),
            ...(e.target.value === form.tts_fallback_engine ? { tts_fallback_engine: '', tts_fallback_voice: '' } : {}),
          })}>
          {TTS_ENGINES.map((opt) => <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>)}
        </TextField>
        <VoiceField label="Voix" engine={form.tts_short_engine} value={form.tts_short_voice}
          onChange={(voice) => update({ tts_short_voice: voice })}
          azureVoices={azureVoices} geminiVoices={geminiVoices} />
      </Box>

      {elevenLabsKeyMissing && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          Aucune clé ElevenLabs enregistrée : ajoutez la vôtre dans Compte → Clés API, sinon la voix de secours sera utilisée.
        </Alert>
      )}

      {form.tts_short_engine === 'elevenlabs' && !form.tts_short_voice.trim() && (
        <Alert severity="warning" sx={{ mb: 3 }}>Renseignez le Voice ID ElevenLabs, sinon la voix de secours sera utilisée.</Alert>
      )}

      <Typography variant="subtitle1" sx={{ mb: 1 }}>Voix de secours</Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Lit toute la narration si le moteur ci-dessus refuse (clé invalide, crédit épuisé). Elle doit utiliser un autre
        moteur. Sans voix de secours : Gemini puis Edge TTS, avec les voix par défaut.
      </Typography>
      <Box sx={{ display: 'flex', gap: 2, mb: 3 }}>
        <TextField select fullWidth label="Moteur de secours" value={form.tts_fallback_engine}
          onChange={(e) => update({ tts_fallback_engine: e.target.value, tts_fallback_voice: '' })}>
          <MenuItem value="">Aucun</MenuItem>
          {TTS_ENGINES.filter((opt) => opt.value !== form.tts_short_engine).map((opt) => (
            <MenuItem key={opt.value} value={opt.value}>{opt.label}</MenuItem>
          ))}
        </TextField>
        {form.tts_fallback_engine && (
          <VoiceField label="Voix de secours" engine={form.tts_fallback_engine} value={form.tts_fallback_voice}
            onChange={(voice) => update({ tts_fallback_voice: voice })}
            azureVoices={azureVoices} geminiVoices={geminiVoices} />
        )}
      </Box>
      {form.tts_fallback_engine && !form.tts_fallback_voice.trim() && (
        <Alert severity="warning" sx={{ mb: 3 }}>Choisissez une voix : sans elle, ce secours ne sera pas enregistré.</Alert>
      )}
    </>
  )
}
