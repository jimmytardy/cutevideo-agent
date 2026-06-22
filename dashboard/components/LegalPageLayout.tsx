import Box from '@mui/material/Box'
import Container from '@mui/material/Container'
import Link from '@mui/material/Link'
import Typography from '@mui/material/Typography'
import NextLink from 'next/link'

const SITE_URL = 'https://cutevideo.jimmy-tardy-informatique.fr'

type LegalPageLayoutProps = {
  title: string
  updatedAt: string
  children: React.ReactNode
}

export function LegalPageLayout({ title, updatedAt, children }: LegalPageLayoutProps) {
  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', py: 6 }}>
      <Container maxWidth="md">
        <Typography variant="overline" color="text.secondary">
          CuteVideo Agent
        </Typography>
        <Typography variant="h3" component="h1" sx={{ mb: 1, fontWeight: 700 }}>
          {title}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 4 }}>
          Dernière mise à jour : {updatedAt}
        </Typography>
        <Box
          sx={{
            '& h2': { typography: 'h5', mt: 4, mb: 1.5, fontWeight: 600 },
            '& h3': { typography: 'h6', mt: 3, mb: 1, fontWeight: 600 },
            '& p, & li': { typography: 'body1', color: 'text.primary', lineHeight: 1.7 },
            '& ul': { pl: 3, my: 1.5 },
            '& a': { color: 'primary.main' },
          }}
        >
          {children}
        </Box>
        <Box sx={{ mt: 6, pt: 3, borderTop: 1, borderColor: 'divider', display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <Link component={NextLink} href="/terms">
            Conditions d&apos;utilisation
          </Link>
          <Link component={NextLink} href="/privacy">
            Politique de confidentialité
          </Link>
          <Link href={SITE_URL}>Retour à l&apos;application</Link>
        </Box>
      </Container>
    </Box>
  )
}

export { SITE_URL }
