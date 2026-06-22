import type { Metadata } from 'next'
import { LegalPageLayout, SITE_URL } from '@/components/LegalPageLayout'

export const metadata: Metadata = {
  title: 'Conditions générales d\'utilisation — CuteVideo Agent',
  description: 'Conditions générales d\'utilisation du service CuteVideo Agent',
}

export default function TermsPage() {
  return (
    <LegalPageLayout title="Conditions générales d&apos;utilisation" updatedAt="22 juin 2026">
      <p>
        Les présentes conditions générales d&apos;utilisation (« CGU ») régissent l&apos;accès et
        l&apos;utilisation du service <strong>CuteVideo Agent</strong>, accessible à l&apos;adresse{' '}
        <a href={SITE_URL}>{SITE_URL}</a>, édité par <strong>Jimmy Tardy Informatique</strong>{' '}
        (« l&apos;Éditeur »).
      </p>

      <h2>1. Objet du service</h2>
      <p>
        CuteVideo Agent est une plateforme en ligne permettant de créer, gérer et publier des contenus
        vidéo à partir d&apos;assistants automatisés (intelligence artificielle, montage, voix off,
        publication sur réseaux sociaux). Le service est destiné aux créateurs et professionnels
        souhaitant produire des vidéos éducatives ou de divertissement.
      </p>

      <h2>2. Acceptation</h2>
      <p>
        En créant un compte ou en utilisant le service, vous acceptez sans réserve les présentes CGU.
        Si vous n&apos;acceptez pas ces conditions, vous ne devez pas utiliser le service.
      </p>

      <h2>3. Compte utilisateur</h2>
      <ul>
        <li>Vous devez fournir des informations exactes lors de l&apos;inscription.</li>
        <li>Vous êtes responsable de la confidentialité de vos identifiants.</li>
        <li>
          Vous pouvez connecter des comptes tiers (Google/YouTube, TikTok, Instagram) via OAuth ;
          vous garantissez disposer des droits nécessaires sur ces comptes.
        </li>
      </ul>

      <h2>4. Connexions à des services tiers</h2>
      <p>
        Le service peut interagir avec YouTube, TikTok, Instagram et d&apos;autres plateformes via
        leurs API respectives et des prestataires techniques (notamment Composio pour TikTok). L&apos;usage
        de ces intégrations est soumis aux conditions des plateformes concernées. L&apos;Éditeur n&apos;est
        pas responsable des modifications, suspensions ou refus opérés par ces tiers.
      </p>

      <h2>5. Contenus générés et publiés</h2>
      <ul>
        <li>Vous restez seul responsable des contenus créés, publiés ou diffusés via votre compte.</li>
        <li>
          Vous vous engagez à respecter les lois applicables, les droits d&apos;auteur, la vie privée
          et les règles des plateformes de diffusion.
        </li>
        <li>
          Les contenus générés par IA peuvent contenir des erreurs ; vous devez les vérifier avant
          publication.
        </li>
      </ul>

      <h2>6. Propriété intellectuelle</h2>
      <p>
        Le service, son interface, son code et sa marque restent la propriété de l&apos;Éditeur. Sous
        réserve des droits des tiers (musiques, images, API), vous conservez vos droits sur les
        contenus que vous fournissez ou validez pour publication.
      </p>

      <h2>7. Disponibilité et évolution</h2>
      <p>
        Le service est fourni « en l&apos;état ». L&apos;Éditeur s&apos;efforce d&apos;assurer une
        disponibilité raisonnable mais ne garantit pas un fonctionnement ininterrompu. Des
        maintenance, mises à jour ou limitations techniques peuvent survenir sans préavis.
      </p>

      <h2>8. Limitation de responsabilité</h2>
      <p>
        Dans les limites autorisées par la loi, l&apos;Éditeur ne pourra être tenu responsable des
        dommages indirects, pertes de données, pertes d&apos;exploitation, ou sanctions imposées par
        une plateforme tierce du fait de contenus publiés par l&apos;utilisateur.
      </p>

      <h2>9. Résiliation</h2>
      <p>
        Vous pouvez cesser d&apos;utiliser le service à tout moment. L&apos;Éditeur peut suspendre ou
        résilier un accès en cas de violation des CGU, de fraude ou de risque pour la sécurité du
        service.
      </p>

      <h2>10. Données personnelles</h2>
      <p>
        Le traitement de vos données est décrit dans la{' '}
        <a href={`${SITE_URL}/privacy`}>politique de confidentialité</a>.
      </p>

      <h2>11. Droit applicable</h2>
      <p>
        Les présentes CGU sont soumises au droit français. En cas de litige, et à défaut de résolution
        amiable, les tribunaux compétents seront ceux du ressort du siège de l&apos;Éditeur, sous réserve
        des dispositions impératives protectrices des consommateurs.
      </p>

      <h2>12. Contact</h2>
      <p>
        Pour toute question relative aux CGU :{' '}
        <a href="mailto:tardyjim26@gmail.com">tardyjim26@gmail.com</a>
      </p>
    </LegalPageLayout>
  )
}
