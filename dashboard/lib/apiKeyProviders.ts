export type ApiKeyProviderId =
  | 'gemini'
  | 'anthropic'
  | 'fal'
  | 'gcp'
  | 'azure_speech'
  | 'postforme'
  | 'zernio'

export type ApiKeyProviderInfo = {
  id: ApiKeyProviderId
  label: string
  shortDescription: string
  keyFieldLabel: string
  tutorialTitle: string
  steps: string[]
  docUrl: string
  docLabel: string
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
    shortDescription: 'Modèles Claude pour les agents de rédaction et de critique (option premium).',
    keyFieldLabel: 'Clé API Anthropic',
    tutorialTitle: 'Obtenir une clé Anthropic',
    steps: [
      'Créez un compte sur la console Anthropic (facturation requise pour l’usage API).',
      'Allez dans Settings → API keys.',
      'Cliquez sur « Create Key », donnez-lui un nom, puis copiez la clé (sk-ant-…).',
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
      'Notez aussi la région (ex. westeurope) : elle peut être demandée dans la configuration de la chaîne.',
    ],
    docUrl: 'https://portal.azure.com/#create/Microsoft.CognitiveServicesSpeechServices',
    docLabel: 'Portail Azure — créer une ressource Speech',
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
]

const providerById = new Map(API_KEY_PROVIDERS.map((p) => [p.id, p]))

export function getApiKeyProvider(id: string): ApiKeyProviderInfo | undefined {
  return providerById.get(id as ApiKeyProviderId)
}

export function getApiKeyProviderLabel(id: string): string {
  return getApiKeyProvider(id)?.label ?? id
}
