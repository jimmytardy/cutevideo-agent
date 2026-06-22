import type { Metadata } from 'next'
import { LegalPageLayout, SITE_URL } from '@/components/LegalPageLayout'

export const metadata: Metadata = {
  title: 'Politique de confidentialité — CuteVideo Agent',
  description: 'Politique de confidentialité du service CuteVideo Agent',
}

export default function PrivacyPage() {
  return (
    <LegalPageLayout title="Politique de confidentialité" updatedAt="22 juin 2026">
      <p>
        La présente politique de confidentialité décrit comment <strong>Jimmy Tardy Informatique</strong>{' '}
        (« nous », « l&apos;Éditeur ») traite les données personnelles dans le cadre du service{' '}
        <strong>CuteVideo Agent</strong> ({SITE_URL}).
      </p>

      <h2>1. Responsable du traitement</h2>
      <p>
        <strong>Jimmy Tardy Informatique</strong>
        <br />
        Contact :{' '}
        <a href="mailto:tardyjim26@gmail.com">tardyjim26@gmail.com</a>
      </p>

      <h2>2. Données collectées</h2>
      <p>Selon votre utilisation du service, nous pouvons traiter :</p>
      <ul>
        <li>
          <strong>Données de compte</strong> : adresse e-mail, nom affiché, photo de profil (via
          connexion Google), identifiant interne.
        </li>
        <li>
          <strong>Données de chaîne / projet</strong> : noms, thèmes, briefs créatifs, paramètres de
          publication, métadonnées vidéo.
        </li>
        <li>
          <strong>Données de connexion aux plateformes</strong> : identifiants techniques et jetons
          OAuth (YouTube, TikTok via Composio, Instagram) nécessaires à la publication et à la gestion
          de vos comptes connectés. Les mots de passe de ces services ne sont jamais collectés.
        </li>
        <li>
          <strong>Données techniques</strong> : journaux serveur, adresse IP, horodatages, identifiants
          de session, afin d&apos;assurer la sécurité et le bon fonctionnement.
        </li>
        <li>
          <strong>Contenus</strong> : scripts, médias, vidéos générées et fichiers associés au pipeline
          de production.
        </li>
      </ul>

      <h2>3. Finalités et bases légales</h2>
      <ul>
        <li>
          <strong>Fourniture du service</strong> (exécution du contrat) : création de compte, génération
          vidéo, publication sur les plateformes que vous connectez.
        </li>
        <li>
          <strong>Authentification OAuth</strong> (exécution du contrat / intérêt légitime) : liaison
          sécurisée avec Google, TikTok, Instagram.
        </li>
        <li>
          <strong>Amélioration et sécurité</strong> (intérêt légitime) : journalisation, prévention des
          abus, correction d&apos;erreurs.
        </li>
        <li>
          <strong>Support</strong> (intérêt légitime / contrat) : réponse à vos demandes.
        </li>
      </ul>

      <h2>4. Sous-traitants et destinataires</h2>
      <p>Vos données peuvent être traitées par des prestataires techniques, notamment :</p>
      <ul>
        <li>Hébergeur du serveur et base de données</li>
        <li>Fournisseurs d&apos;IA et de synthèse (ex. Google Gemini, Anthropic selon configuration)</li>
        <li>Stockage objet (ex. Amazon S3, si activé)</li>
        <li>Composio (connexion et actions TikTok)</li>
        <li>Google (authentification et API YouTube)</li>
        <li>Meta / Instagram (selon configuration)</li>
      </ul>
      <p>
        Ces prestataires n&apos;accèdent qu&apos;aux données nécessaires à leur mission et dans le cadre
        de obligations contractuelles de confidentialité et de sécurité.
      </p>

      <h2>5. Durées de conservation</h2>
      <ul>
        <li>Compte actif : conservation tant que le compte existe, puis suppression ou anonymisation.</li>
        <li>Jetons OAuth : conservés tant que la connexion à une plateforme est active ; supprimables à la déconnexion.</li>
        <li>Vidéos et médias : selon la configuration de rétention (ex. purge automatique après N jours).</li>
        <li>Journaux techniques : durée limitée, généralement inférieure à 12 mois.</li>
      </ul>

      <h2>6. Vos droits (RGPD)</h2>
      <p>
        Conformément au Règlement général sur la protection des données, vous disposez des droits
        d&apos;accès, de rectification, d&apos;effacement, de limitation, d&apos;opposition et de
        portabilité, lorsque applicable.
      </p>
      <p>
        Pour exercer vos droits :{' '}
        <a href="mailto:tardyjim26@gmail.com">tardyjim26@gmail.com</a>.
        Vous pouvez également introduire une réclamation auprès de la CNIL (
        <a href="https://www.cnil.fr" rel="noopener noreferrer">
          www.cnil.fr
        </a>
        ).
      </p>

      <h2>7. Cookies et stockage local</h2>
      <p>
        Le service utilise un jeton d&apos;authentification stocké localement dans votre navigateur
        (localStorage) pour maintenir votre session. Aucun cookie publicitaire n&apos;est déposé par
        défaut par CuteVideo Agent.
      </p>

      <h2>8. Sécurité</h2>
      <p>
        Nous mettons en œuvre des mesures techniques et organisationnelles raisonnables (chiffrement
        des communications HTTPS, contrôle d&apos;accès, secrets serveur) pour protéger vos données.
        Aucune transmission sur Internet n&apos;est toutefois totalement exempte de risque.
      </p>

      <h2>9. Transferts hors Union européenne</h2>
      <p>
        Certains sous-traitants (ex. fournisseurs cloud ou IA) peuvent être situés hors UE. Dans ce
        cas, des garanties appropriées (clauses contractuelles types ou équivalent) sont recherchées
        conformément à la réglementation applicable.
      </p>

      <h2>10. Modifications</h2>
      <p>
        Cette politique peut être mise à jour. La date en tête de page indique la dernière révision.
        L&apos;usage continu du service après modification vaut prise de connaissance.
      </p>

      <h2>11. Contact</h2>
      <p>
        Questions relatives à la vie privée :{' '}
        <a href="mailto:tardyjim26@gmail.com">tardyjim26@gmail.com</a>
      </p>
    </LegalPageLayout>
  )
}
