'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Box from '@mui/material/Box'
import Typography from '@mui/material/Typography'
import Button from '@mui/material/Button'
import TextField from '@mui/material/TextField'
import Stepper from '@mui/material/Stepper'
import Step from '@mui/material/Step'
import StepLabel from '@mui/material/StepLabel'
import Card from '@mui/material/Card'
import CardContent from '@mui/material/CardContent'
import CardActionArea from '@mui/material/CardActionArea'
import Alert from '@mui/material/Alert'
import CircularProgress from '@mui/material/CircularProgress'
import MenuItem from '@mui/material/MenuItem'
import FormControlLabel from '@mui/material/FormControlLabel'
import Checkbox from '@mui/material/Checkbox'
import Radio from '@mui/material/Radio'
import RadioGroup from '@mui/material/RadioGroup'
import FormControl from '@mui/material/FormControl'
import FormLabel from '@mui/material/FormLabel'
import Link from '@mui/material/Link'
import AppShell from '@/components/AppShell'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import {
  analyzeMarket,
  applyYoutubeBranding,
  completeOnboarding,
  connectTikTok,
  createOnboardingDraft,
  generateBrandKit,
  getYoutubeOAuthUrl,
  listYoutubeChannels,
  patchOnboardingInstagram,
  patchOnboardingTiktok,
  patchOnboardingYoutube,
  suggestThemes,
  type ChannelBrandKit,
  type MarketAnalysisReport,
  type ThemeVariant,
  type YouTubeChannelItem,
} from '@/lib/api'

const STEPS = ['Thème', 'Identité', 'YouTube', 'TikTok', 'Instagram', 'Terminer']

export default function NewChannelWizardPage() {
  const router = useRouter()
  const [activeStep, setActiveStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const [themePrompt, setThemePrompt] = useState('')
  const [marketReport, setMarketReport] = useState<MarketAnalysisReport | null>(null)
  const [variants, setVariants] = useState<ThemeVariant[]>([])
  const [selectedVariant, setSelectedVariant] = useState<ThemeVariant | null>(null)
  const [brandKit, setBrandKit] = useState<ChannelBrandKit | null>(null)
  const [channelId, setChannelId] = useState<string | null>(null)

  const [ytMode, setYtMode] = useState<'existing' | 'new'>('existing')
  const [ytChannels, setYtChannels] = useState<YouTubeChannelItem[]>([])
  const [selectedYtId, setSelectedYtId] = useState('')

  const [tiktokPrivacy, setTiktokPrivacy] = useState('PUBLIC_TO_EVERYONE')
  const [tiktokHashtags, setTiktokHashtags] = useState('')
  const [tiktokDisableComment, setTiktokDisableComment] = useState(false)

  const [igPageId, setIgPageId] = useState('')
  const [igPageName, setIgPageName] = useState('')
  const [igBio, setIgBio] = useState('')

  const marketContextForSuggest = (): string | undefined => {
    if (!marketReport) return undefined
    return [
      marketReport.market_summary,
      `Verdict différenciation : ${marketReport.differentiation_verdict}`,
      `Saturation : ${marketReport.saturation_verdict}`,
      marketReport.avoid.length ? `À éviter : ${marketReport.avoid.join('; ')}` : '',
    ]
      .filter(Boolean)
      .join('\n')
  }

  const handleMarketAnalysis = async () => {
    if (!themePrompt.trim()) return
    setLoading(true)
    setError(null)
    try {
      const report = await analyzeMarket(themePrompt.trim())
      setMarketReport(report)
      const fromReport: ThemeVariant[] = report.recommended_themes.map((t) => ({
        content_angle: t.content_angle,
        slug: t.slug,
        name: t.name,
        theme_category: t.theme_category,
        niche_prompt: t.niche_prompt,
        suggested_tags: t.suggested_tags,
      }))
      setVariants(fromReport)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur analyse marché')
    } finally {
      setLoading(false)
    }
  }

  const handleSuggest = async () => {
    if (!themePrompt.trim()) return
    setLoading(true)
    setError(null)
    try {
      const v = await suggestThemes(themePrompt.trim(), marketContextForSuggest())
      setVariants(v)
      setActiveStep(0)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur IA')
    } finally {
      setLoading(false)
    }
  }

  const handleSelectRecommendedTheme = async (
    theme: MarketAnalysisReport['recommended_themes'][number],
  ) => {
    const variant: ThemeVariant = {
      content_angle: theme.content_angle,
      slug: theme.slug,
      name: theme.name,
      theme_category: theme.theme_category,
      niche_prompt: theme.niche_prompt,
      suggested_tags: theme.suggested_tags,
    }
    await handleSelectVariant(variant)
  }

  const handleSelectVariant = async (variant: ThemeVariant) => {
    setSelectedVariant(variant)
    setLoading(true)
    setError(null)
    try {
      const kit = await generateBrandKit(variant, marketContextForSuggest())
      setBrandKit(kit)
      setActiveStep(1)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur génération kit')
    } finally {
      setLoading(false)
    }
  }

  const handleSaveDraft = async () => {
    if (!brandKit) return
    setLoading(true)
    setError(null)
    try {
      const ch = await createOnboardingDraft(themePrompt, brandKit)
      setChannelId(ch.id)
      setActiveStep(2)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur création brouillon')
    } finally {
      setLoading(false)
    }
  }

  const handleYoutubeOAuth = async () => {
    if (!channelId) return
    const { authorization_url } = await getYoutubeOAuthUrl(channelId)
    window.open(authorization_url, '_blank', 'noopener,noreferrer')
  }

  const handleRefreshYtList = async () => {
    if (!channelId) return
    setLoading(true)
    setError(null)
    try {
      const list = await listYoutubeChannels(channelId)
      setYtChannels(list)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Liste YouTube indisponible')
    } finally {
      setLoading(false)
    }
  }

  const handleYoutubeNext = async () => {
    if (!channelId || !selectedYtId) return
    setLoading(true)
    setError(null)
    try {
      const item = ytChannels.find((c) => c.channel_id === selectedYtId)
      await patchOnboardingYoutube(channelId, {
        youtube_channel_id: selectedYtId,
        youtube_channel_url: item?.custom_url
          ? `https://youtube.com/${item.custom_url}`
          : `https://youtube.com/channel/${selectedYtId}`,
      })
      if (brandKit) {
        await applyYoutubeBranding(channelId)
      }
      setActiveStep(3)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur YouTube')
    } finally {
      setLoading(false)
    }
  }

  const handleTiktokNext = async () => {
    if (!channelId) return
    setLoading(true)
    setError(null)
    try {
      await patchOnboardingTiktok(channelId, {
        privacy_level: tiktokPrivacy,
        disable_comment: tiktokDisableComment,
        default_hashtags: tiktokHashtags.split(/[\s,]+/).filter(Boolean),
      })
      setActiveStep(4)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur TikTok')
    } finally {
      setLoading(false)
    }
  }

  const handleInstagramNext = async () => {
    if (!channelId || !igPageId.trim()) return
    setLoading(true)
    setError(null)
    try {
      await patchOnboardingInstagram(channelId, {
        instagram_page_id: igPageId.trim(),
        instagram_profile: {
          page_name: igPageName || brandKit?.instagram.page_name,
          bio: igBio || brandKit?.instagram.bio,
          page_id: igPageId.trim(),
        },
      })
      setActiveStep(5)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur Instagram')
    } finally {
      setLoading(false)
    }
  }

  const handleFinish = async () => {
    if (!channelId) return
    setLoading(true)
    setError(null)
    try {
      await completeOnboarding(channelId)
      router.push('/channels')
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Erreur finalisation')
    } finally {
      setLoading(false)
    }
  }

  const updateBrandField = (path: string, value: string) => {
    if (!brandKit) return
    const next = { ...brandKit }
    const parts = path.split('.')
    if (parts.length === 2) {
      const [section, field] = parts
      const sectionObj = { ...(next as Record<string, Record<string, string>>)[section] }
      sectionObj[field] = value
      ;(next as Record<string, unknown>)[section] = sectionObj
    } else {
      ;(next as Record<string, string>)[path] = value
    }
    setBrandKit(next)
  }

  return (
    <AppShell>
      <Box sx={{ maxWidth: 800, mx: 'auto' }}>
        <Typography variant="h5" sx={{ mb: 3 }}>
          Créer une chaîne guidée
        </Typography>

        <Stepper activeStep={activeStep} sx={{ mb: 4 }}>
          {STEPS.map((label) => (
            <Step key={label}>
              <StepLabel>{label}</StepLabel>
            </Step>
          ))}
        </Stepper>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}

        {activeStep === 0 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField
              label="Décrivez votre idée de chaîne"
              placeholder="Vidéos d'animaux mignons bébé, montages courts..."
              multiline
              rows={4}
              fullWidth
              value={themePrompt}
              onChange={(e) => setThemePrompt(e.target.value)}
            />
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              <Button
                variant="contained"
                color="secondary"
                onClick={handleMarketAnalysis}
                disabled={loading || !themePrompt.trim()}
              >
                {loading ? <CircularProgress size={24} /> : 'Analyser le marché et la concurrence'}
              </Button>
              <Button variant="outlined" onClick={handleSuggest} disabled={loading || !themePrompt.trim()}>
                Proposer des niches (rapide)
              </Button>
            </Box>
            <Alert severity="info" sx={{ mt: 1 }}>
              L&apos;analyse marché utilise l&apos;API YouTube (données réelles) + synthèse TikTok/Instagram.
              Configurez <code>YOUTUBE_REFRESH_TOKEN</code> sur le serveur pour les données concurrents YouTube.
            </Alert>
            {marketReport && (
              <Card variant="outlined" sx={{ mt: 2 }}>
                <CardContent>
                  <Typography variant="h6" gutterBottom>
                    Analyse marché
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap', mb: 2 }}>
                    <Chip
                      label={`Saturation : ${marketReport.saturation_verdict}`}
                      color={
                        marketReport.saturation_verdict === 'favorable'
                          ? 'success'
                          : marketReport.saturation_verdict === 'crowded'
                            ? 'error'
                            : 'warning'
                      }
                      size="small"
                    />
                    {marketReport.platforms_analyzed.map((p) => (
                      <Chip key={p} label={p} size="small" variant="outlined" />
                    ))}
                  </Box>
                  <Typography variant="body2" paragraph>
                    {marketReport.market_summary}
                  </Typography>
                  <Typography variant="subtitle2" color="primary" gutterBottom>
                    Chance de se démarquer
                  </Typography>
                  <Typography variant="body2" paragraph>
                    {marketReport.differentiation_verdict}
                  </Typography>
                  {marketReport.top_competitors.length > 0 && (
                    <>
                      <Divider sx={{ my: 2 }} />
                      <Typography variant="subtitle2" gutterBottom>
                        Concurrence principale
                      </Typography>
                      {marketReport.top_competitors.slice(0, 5).map((c) => (
                        <Box key={`${c.platform}-${c.name}`} sx={{ mb: 1.5 }}>
                          <Typography variant="body2" fontWeight={600}>
                            {c.name} ({c.platform})
                            {c.subscriber_count != null
                              ? ` — ${c.subscriber_count.toLocaleString('fr-FR')} abonnés`
                              : ''}
                          </Typography>
                          <Typography variant="caption" color="text.secondary">
                            {c.positioning}
                          </Typography>
                        </Box>
                      ))}
                    </>
                  )}
                  {marketReport.avoid.length > 0 && (
                    <Alert severity="warning" sx={{ mt: 2 }}>
                      À éviter : {marketReport.avoid.join(' · ')}
                    </Alert>
                  )}
                </CardContent>
              </Card>
            )}
            {variants.length > 0 && (
              <Box sx={{ display: 'grid', gap: 2, mt: 2 }}>
                {marketReport?.recommended_themes.map((t) => (
                  <Card key={t.slug} variant="outlined">
                    <CardActionArea
                      onClick={() => handleSelectRecommendedTheme(t)}
                      disabled={loading}
                    >
                      <CardContent>
                        <Box sx={{ display: 'flex', gap: 1, mb: 1 }}>
                          <Chip
                            label={`Diff. ${t.differentiation_score}/100`}
                            size="small"
                            color={t.differentiation_score >= 70 ? 'success' : 'default'}
                          />
                          <Chip label={t.competition_level} size="small" variant="outlined" />
                        </Box>
                        <Typography variant="h6">{t.name}</Typography>
                        <Typography variant="body2" color="text.secondary">
                          {t.content_angle}
                        </Typography>
                        <Typography variant="body2" sx={{ mt: 1 }}>
                          {t.why_you_can_win}
                        </Typography>
                        <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                          {t.theme_category} — {t.slug}
                        </Typography>
                      </CardContent>
                    </CardActionArea>
                  </Card>
                ))}
                {!marketReport &&
                  variants.map((v) => (
                    <Card key={v.slug} variant="outlined">
                      <CardActionArea onClick={() => handleSelectVariant(v)} disabled={loading}>
                        <CardContent>
                          <Typography variant="h6">{v.name}</Typography>
                          <Typography variant="body2" color="text.secondary">
                            {v.content_angle}
                          </Typography>
                          <Typography variant="caption" display="block" sx={{ mt: 1 }}>
                            {v.theme_category} — {v.slug}
                          </Typography>
                        </CardContent>
                      </CardActionArea>
                    </Card>
                  ))}
              </Box>
            )}
          </Box>
        )}

        {activeStep === 1 && brandKit && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <TextField label="Nom" fullWidth value={brandKit.name} onChange={(e) => updateBrandField('name', e.target.value)} />
            <TextField label="Slug" fullWidth value={brandKit.slug} onChange={(e) => updateBrandField('slug', e.target.value)} />
            <TextField
              label="Titre YouTube"
              fullWidth
              value={brandKit.youtube.title}
              onChange={(e) => updateBrandField('youtube.title', e.target.value)}
            />
            <TextField
              label="Description YouTube"
              fullWidth
              multiline
              rows={4}
              value={brandKit.youtube.description}
              onChange={(e) => updateBrandField('youtube.description', e.target.value)}
            />
            <TextField
              label="Bio TikTok"
              fullWidth
              value={brandKit.tiktok.bio}
              onChange={(e) => updateBrandField('tiktok.bio', e.target.value)}
            />
            <TextField
              label="Bio Instagram"
              fullWidth
              value={brandKit.instagram.bio}
              onChange={(e) => updateBrandField('instagram.bio', e.target.value)}
            />
            <Button variant="contained" onClick={handleSaveDraft} disabled={loading}>
              Continuer vers YouTube
            </Button>
          </Box>
        )}

        {activeStep === 2 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <FormControl>
              <FormLabel>Type de chaîne YouTube</FormLabel>
              <RadioGroup value={ytMode} onChange={(e) => setYtMode(e.target.value as 'existing' | 'new')}>
                <FormControlLabel value="existing" control={<Radio />} label="Chaîne existante sur mon compte Google" />
                <FormControlLabel
                  value="new"
                  control={<Radio />}
                  label="Nouvelle sous-chaîne Brand (à créer dans YouTube Studio)"
                />
              </RadioGroup>
            </FormControl>
            {ytMode === 'new' && brandKit && (
              <Alert severity="info">
                Créez une chaîne avec le nom suggéré « {brandKit.youtube.title} » puis revenez ici.
                <Link href="https://www.youtube.com/channel_switcher" target="_blank" rel="noopener" sx={{ ml: 1 }}>
                  Ouvrir le sélecteur de chaînes
                </Link>
              </Alert>
            )}
            <Button variant="outlined" onClick={handleYoutubeOAuth}>
              Connecter Google (OAuth)
            </Button>
            <Button variant="outlined" onClick={handleRefreshYtList} disabled={loading}>
              Rafraîchir la liste des chaînes
            </Button>
            <TextField
              select
              label="Chaîne YouTube"
              fullWidth
              value={selectedYtId}
              onChange={(e) => setSelectedYtId(e.target.value)}
            >
              {ytChannels.map((c) => (
                <MenuItem key={c.channel_id} value={c.channel_id}>
                  {c.title} {c.custom_url ? `(${c.custom_url})` : ''}
                </MenuItem>
              ))}
            </TextField>
            <Button variant="contained" onClick={handleYoutubeNext} disabled={!selectedYtId || loading}>
              Associer et appliquer le branding
            </Button>
          </Box>
        )}

        {activeStep === 3 && channelId && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Alert severity="info">
              Connectez le compte TikTok de cette chaîne via Composio (un compte par chaîne).
            </Alert>
            <Button
              variant="outlined"
              onClick={async () => {
                const { redirect_url } = await connectTikTok(channelId)
                window.open(redirect_url, '_blank', 'noopener,noreferrer')
              }}
            >
              Connecter TikTok
            </Button>
            <TextField
              select
              label="Confidentialité par défaut"
              fullWidth
              value={tiktokPrivacy}
              onChange={(e) => setTiktokPrivacy(e.target.value)}
            >
              <MenuItem value="PUBLIC_TO_EVERYONE">Public</MenuItem>
              <MenuItem value="MUTUAL_FOLLOW_FRIENDS">Amis mutuels</MenuItem>
              <MenuItem value="FOLLOWER_OF_CREATOR">Abonnés</MenuItem>
              <MenuItem value="SELF_ONLY">Moi uniquement</MenuItem>
            </TextField>
            <TextField
              label="Hashtags par défaut"
              placeholder="#animaux #mignon"
              fullWidth
              value={tiktokHashtags}
              onChange={(e) => setTiktokHashtags(e.target.value)}
            />
            <FormControlLabel
              control={<Checkbox checked={tiktokDisableComment} onChange={(e) => setTiktokDisableComment(e.target.checked)} />}
              label="Désactiver les commentaires par défaut"
            />
            <Button variant="contained" onClick={handleTiktokNext} disabled={loading}>
              Continuer vers Instagram
            </Button>
          </Box>
        )}

        {activeStep === 4 && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Alert severity="warning">
              Instagram requiert une Page Business existante et un token dans le fichier .env du serveur.
            </Alert>
            <TextField label="Instagram Page ID" fullWidth value={igPageId} onChange={(e) => setIgPageId(e.target.value)} />
            <TextField
              label="Nom de la page"
              fullWidth
              value={igPageName}
              onChange={(e) => setIgPageName(e.target.value)}
              placeholder={brandKit?.instagram.page_name}
            />
            <TextField
              label="Bio"
              fullWidth
              multiline
              rows={2}
              value={igBio}
              onChange={(e) => setIgBio(e.target.value)}
              placeholder={brandKit?.instagram.bio}
            />
            <Button variant="contained" onClick={handleInstagramNext} disabled={!igPageId.trim() || loading}>
              Continuer
            </Button>
          </Box>
        )}

        {activeStep === 5 && brandKit && (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <Typography variant="h6">Récapitulatif</Typography>
            <Typography>Nom : {brandKit.name}</Typography>
            <Typography>Slug : {brandKit.slug}</Typography>
            <Typography>Catégorie : {brandKit.theme_category}</Typography>
            <Typography variant="body2" color="text.secondary">
              {brandKit.niche_prompt}
            </Typography>
            <Button variant="contained" color="success" onClick={handleFinish} disabled={loading}>
              Activer la chaîne
            </Button>
          </Box>
        )}
      </Box>
    </AppShell>
  )
}
