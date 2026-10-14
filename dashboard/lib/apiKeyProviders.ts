export type ApiKeyProviderId =
  | 'gemini'
  | 'anthropic'
  | 'fal'
  | 'gcp'
  | 'azure_speech'
  | 'postforme'
  | 'zernio'
  | 'youtube'
  | 'instagram'

/** Champ complémentaire enregistré avec la clé (`metadata` de `PUT /me/api-keys/{provider}`). */
export type ApiKeyMetadataField = {
  key: string
  label: string
  placeholder?: string
  required?: boolean
}

export type ApiKeyProviderInfo = {
  id: ApiKeyProviderId
  label: string
  shortDescription: string
  keyFieldLabel: string
  tutorialTitle: string
  steps: string[]
  docUrl: string
  docLabel: string
  metadataFields?: ApiKeyMetadataField[]
}

export const API_KEY_PROVIDERS: ApiKeyProviderInfo[] = [
  {
    id: 'gemini',
    label: 'Google Gemini',
    shortDescription: 'Modèles Gemini pour les agents, le scoring média et l’analyse vidéo.',
    keyFieldLabel: 'Clé API Gemini',
    tutorialTitle: 'Obtenir une clé Google Gemini',
    steps: [
      'Connectez-vous à Google AI Studio avec votre compte Google.',
      'Ouvrez « Get API key » puis « Create API key » (projet Google Cloud existant ou nouveau).',
      'Copiez la clé générée (elle commence généralement par AIza…).',
      'Collez-la ci-dessus et cliquez sur Enregistrer.',
    ],
    docUrl: 'https://aistudio.google.com/apikey',
    docLabel: 'Google AI Studio — clés API',
  },
  {
    id: 'anthropic',
    label: 'Anthropic Claude',
    shortDescription:
      'Requise pour créer des vidéos (Claude Studio) ; sert aussi aux agents. Facturée sur votre compte Anthropic.',
    keyFieldLabel: 'Clé API Anthropic (sk-ant-api…)',
    tutorialTitle: 'Obtenir une clé Anthropic',
    steps: [
      'Créez un compte sur la console Anthropic (facturation requise pour l’usage API).',
      'Allez dans Settings → API keys.',
      'Cliquez sur « Create Key », donnez-lui un nom, puis copiez la clé (sk-ant-api…). Un token d’abonnement (sk-ant-oat…) n’est pas accepté.',
      'Collez-la ci-dessus — elle ne sera plus visible en entier après enregistrement.',
    ],
    docUrl: 'https://console.anthropic.com/settings/keys',
    docLabel: 'Console Anthropic — clés API',
  },
  {
    id: 'fal',
    label: 'fal.ai (Flux)',
    shortDescription: 'Génération d’images IA de secours via les modèles Flux (Schnell, Pro, Ultra).',
    keyFieldLabel: 'Clé API fal.ai',
    tutorialTitle: 'Obtenir une clé fal.ai',
    steps: [
      'Inscrivez-vous sur fal.ai et ouvrez le tableau de bord.',
      'Allez dans la section « API Keys » (ou Dashboard → Keys).',
      'Créez une nouvelle clé et copiez-la immédiatement.',
      'Collez-la ci-dessus pour activer la génération d’images Flux.',
    ],
    docUrl: 'https://fal.ai/dashboard/keys',
    docLabel: 'fal.ai — clés API',
  },
  {
    id: 'gcp',
    label: 'Google Imagen 3 (Vertex AI)',
    shortDescription: 'Images IA via Imagen 3 sur Google Cloud (compte de service Vertex AI).',
    keyFieldLabel: 'JSON du compte de service',
    tutorialTitle: 'Configurer Google Imagen 3 sur Vertex AI',
    steps: [
      'Dans la console Google Cloud, créez ou sélectionnez un projet et activez l’API Vertex AI.',
      'Créez un compte de service (IAM → Comptes de service → Créer) avec le rôle « Vertex AI User ».',
      'Générez une clé JSON pour ce compte (Clés → Ajouter une clé → Créer une clé JSON).',
      'Collez le contenu complet du fichier JSON ci-dessus (pas seulement le chemin du fichier).',
    ],
    docUrl: 'https://cloud.google.com/vertex-ai/docs/generative-ai/image/overview',
    docLabel: 'Documentation Imagen 3 (Vertex AI)',
    metadataFields: [{ key: 'location', label: 'Région Vertex AI', placeholder: 'europe-west1' }],
  },
  {
    id: 'azure_speech',
    label: 'Azure Speech (voix off)',
    shortDescription: 'Synthèse vocale neuronale Azure pour une voix off de qualité studio.',
    keyFieldLabel: 'Clé Azure Speech',
    tutorialTitle: 'Obtenir une clé Azure Speech',
    steps: [
      'Dans le portail Azure, créez une ressource « Speech » (Speech Services).',
      'Une fois déployée, ouvrez la ressource → « Keys and Endpoint ».',
      'Copiez « Key 1 » (ou Key 2) — c’est la clé à coller ici.',
      'Indiquez aussi la région de la ressource (ex. westeurope).',
    ],
    docUrl: 'https://portal.azure.com/#create/Microsoft.CognitiveServicesSpeechServices',
    docLabel: 'Portail Azure — créer une ressource Speech',
    metadataFields: [{ key: 'region', label: 'Région Azure', placeholder: 'westeurope' }],
  },
  {
    id: 'postforme',
    label: 'Post for Me (TikTok)',
    shortDescription: 'Publication TikTok via l’appli auditée de Post for Me (comptes illimités, ~10 $/mois).',
    keyFieldLabel: 'Clé API Post for Me',
    tutorialTitle: 'Obtenir une clé Post for Me',
    steps: [
      'Créez un compte sur postforme.dev et choisissez le mode « Quickstart » (leurs identifiants TikTok, sans audit).',
      'Ouvrez le tableau de bord → API Keys, puis créez une clé.',
      'Collez-la ci-dessus et enregistrez.',
      'Dans les paramètres de chaque chaîne, choisissez « Post for Me » comme fournisseur TikTok puis connectez le compte.',
    ],
    docUrl: 'https://app.postforme.dev',
    docLabel: 'Post for Me — tableau de bord',
  },
  {
    id: 'zernio',
    label: 'Zernio (TikTok)',
    shortDescription: 'Publication TikTok via Zernio (2 comptes gratuits, puis facturation par compte).',
    keyFieldLabel: 'Clé API Zernio (sk_…)',
    tutorialTitle: 'Obtenir une clé Zernio',
    steps: [
      'Créez un compte sur zernio.com.',
      'Ouvrez Settings → API Keys et créez une clé (elle commence par sk_).',
      'Collez-la ci-dessus et enregistrez.',
      'Dans les paramètres de chaque chaîne, choisissez « Zernio » comme fournisseur TikTok puis connectez le compte.',
    ],
    docUrl: 'https://zernio.com/dashboard',
    docLabel: 'Zernio — tableau de bord',
  },
  {
    id: 'youtube',
    label: 'YouTube (compte Google)',
    shortDescription:
      'Compte Google utilisé pour lister vos chaînes YouTube et publier sur celles qui n’ont pas leur propre connexion OAuth.',
    keyFieldLabel: 'Refresh token OAuth Google',
    tutorialTitle: 'Connecter un compte Google',
    steps: [
      'Le plus simple : connectez chaque chaîne via « Connecter YouTube » dans ses paramètres (OAuth), sans rien saisir ici.',
      'Sinon, générez un refresh token OAuth avec le scope YouTube (youtube.upload) pour l’application de la plateforme.',
      'Collez le refresh token ci-dessus : il sert aux chaînes sans connexion propre.',
    ],
    docUrl: 'https://developers.google.com/youtube/v3/guides/auth/server-side-web-apps',
    docLabel: 'YouTube Data API — OAuth',
  },
  {
    id: 'instagram',
    label: 'Instagram (Graph API)',
    shortDescription: 'Publication des Reels sur votre compte Instagram professionnel.',
    keyFieldLabel: 'Access token Instagram (longue durée)',
    tutorialTitle: 'Obtenir un token Instagram',
    steps: [
      'Reliez votre compte Instagram professionnel à une page Facebook.',
      'Dans Meta for Developers, générez un access token longue durée avec instagram_content_publish.',
      'Collez le token ci-dessus et indiquez l’ID du compte Instagram (page) sur lequel publier.',
    ],
    docUrl: 'https://developers.facebook.com/docs/instagram-platform/content-publishing',
    docLabel: 'Meta — publication de contenu Instagram',
    metadataFields: [{ key: 'page_id', label: 'ID du compte Instagram', placeholder: '17841…', required: true }],
  },
]

const providerById = new Map(API_KEY_PROVIDERS.map((p) => [p.id, p]))

export function getApiKeyProvider(id: string): ApiKeyProviderInfo | undefined {
  return providerById.get(id as ApiKeyProviderId)
}

export function getApiKeyProviderLabel(id: string): string {
  return getApiKeyProvider(id)?.label ?? id
}
