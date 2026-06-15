import type { Metadata } from 'next'
import ThemeRegistry from '@/components/ThemeRegistry'
import SWRProvider from '@/components/SWRProvider'

export const metadata: Metadata = {
  title: 'CuteVideo Agent',
  description: 'Pipeline IA multi-agents de génération de vidéos éducatives',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>
        <ThemeRegistry>
          <SWRProvider>{children}</SWRProvider>
        </ThemeRegistry>
      </body>
    </html>
  )
}
