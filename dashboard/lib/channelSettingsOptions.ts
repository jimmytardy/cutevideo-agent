/** Listes de choix des réglages de chaîne (onglets de /channels/[id]/settings). */

interface Option {
  value: string
  label: string
}

export interface Voice {
  id: string
  label: string
}

export const PLATFORMS = ['youtube', 'tiktok', 'instagram']

export const ANIMATION_MODES: Option[] = [
  { value: '', label: 'Par défaut de la plateforme (scripts libres)' },
  { value: 'scripts', label: 'Scripts libres + modèles' },
  { value: 'templates', label: 'Modèles prêts seulement (titre, compteur, barres, liste)' },
  { value: 'off', label: 'Désactivées (photos et vidéos uniquement)' },
]

export const VISUAL_STYLES: Option[] = [
  { value: '', label: 'Par défaut de la plateforme (animation)' },
  { value: 'animation', label: 'Animation : schémas et animations, photos réelles ponctuelles' },
  { value: 'mixed', label: 'Mixte : photos et vidéos réelles + animations pour les chiffres' },
  { value: 'realistic', label: 'Réaliste : images réelles sur presque tous les plans' },
]

export const PRODUCTION_MODES: Option[] = [
  { value: 'mixed', label: 'Mixte (long + shorts)' },
  { value: 'long_only', label: 'Longues uniquement' },
  { value: 'shorts_only', label: 'Shorts uniquement' },
]

export const YOUTUBE_CATEGORIES: Option[] = [
  { value: '1', label: 'Film & Animation' },
  { value: '2', label: 'Autos & Vehicles' },
  { value: '10', label: 'Music' },
  { value: '15', label: 'Pets & Animals' },
  { value: '17', label: 'Sports' },
  { value: '19', label: 'Travel & Events' },
  { value: '20', label: 'Gaming' },
  { value: '22', label: 'People & Blogs' },
  { value: '23', label: 'Comedy' },
  { value: '24', label: 'Entertainment' },
  { value: '25', label: 'News & Politics' },
  { value: '26', label: 'Howto & Style' },
  { value: '27', label: 'Education' },
  { value: '28', label: 'Science & Technology' },
  { value: '29', label: 'Nonprofits & Activism' },
]

export const AI_PLANS: (Option & { family: string })[] = [
  { value: 'off', label: 'Désactivé', family: '' },
  { value: 'flux_schnell', label: 'Flux Schnell (budget)', family: 'Flux' },
  { value: 'flux_2_dev', label: 'FLUX 2 Dev (bon rapport qualité/prix)', family: 'Flux' },
  { value: 'flux_pro', label: 'FLUX.2 Pro (standard)', family: 'Flux' },
  { value: 'flux_ultra', label: 'Flux Pro Ultra (qualité max)', family: 'Flux' },
  { value: 'imagen3_fast', label: 'Imagen 3 Fast (budget Google)', family: 'Google Imagen 3' },
  { value: 'imagen3', label: 'Imagen 3 (standard Google)', family: 'Google Imagen 3' },
]

export const TTS_ENGINES: Option[] = [
  { value: 'azure', label: 'Azure Neural' },
  { value: 'gemini', label: 'Gemini Flash TTS' },
  { value: 'edge-tts', label: 'Edge TTS (gratuit)' },
]

export function voiceOptionsForEngine(engine: string, azureVoices?: Voice[], geminiVoices?: Voice[]): Voice[] {
  if (engine === 'gemini') return geminiVoices || []
  return azureVoices || []
}
