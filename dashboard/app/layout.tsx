import type { Metadata } from 'next'
import { Inter } from 'next/font/google'
import InitColorSchemeScript from '@mui/material/InitColorSchemeScript'
import ThemeRegistry from '@/components/ThemeRegistry'
import SWRProvider from '@/components/SWRProvider'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
  display: 'swap',
})

export const metadata: Metadata = {
  title: 'CuteVideo Agent',
  description: 'Pipeline IA multi-agents de génération de vidéos éducatives',
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr" suppressHydrationWarning className={inter.variable}>
      <body>
        <InitColorSchemeScript defaultMode="system" modeStorageKey="cutevideo-theme-mode" />
        <ThemeRegistry>
          <SWRProvider>{children}</SWRProvider>
        </ThemeRegistry>
      </body>
    </html>
  )
}
