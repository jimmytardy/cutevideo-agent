'use client'

import AppBar from '@mui/material/AppBar'
import Box from '@mui/material/Box'
import Button from '@mui/material/Button'
import Chip from '@mui/material/Chip'
import Drawer from '@mui/material/Drawer'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import HomeIcon from '@mui/icons-material/Home'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import TvIcon from '@mui/icons-material/Tv'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import BarChartIcon from '@mui/icons-material/BarChart'
import SearchIcon from '@mui/icons-material/Search'
import SettingsIcon from '@mui/icons-material/Settings'
import ScheduleIcon from '@mui/icons-material/Schedule'
import AddCircleIcon from '@mui/icons-material/AddCircle'
import PersonIcon from '@mui/icons-material/Person'
import KeyIcon from '@mui/icons-material/Key'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { clearAuthToken, fetcher, type AuthUser } from '@/lib/api'

const DRAWER_WIDTH = 220
const BASE = '/api/v1'

const NAV_ITEMS = [
  { label: 'Accueil', href: '/', icon: <HomeIcon />, adminOnly: false },
  { label: 'Créer une vidéo', href: '/create', icon: <AddCircleIcon color="primary" />, adminOnly: false },
  { label: 'Chaînes', href: '/channels', icon: <TvIcon />, adminOnly: false },
  { label: 'Marchés analysés', href: '/markets', icon: <SearchIcon />, adminOnly: false },
  { label: 'Projets', href: '/projects', icon: <VideoLibraryIcon />, adminOnly: false },
  { label: 'Mon compte', href: '/account', icon: <PersonIcon />, adminOnly: false },
  { label: 'Clés API', href: '/account/api-keys', icon: <KeyIcon />, adminOnly: false },
  { label: 'Agents', href: '/agents', icon: <SmartToyIcon />, adminOnly: false },
  { label: 'Scheduler', href: '/scheduler', icon: <ScheduleIcon />, adminOnly: true },
  { label: 'Analytics', href: '/analytics', icon: <BarChartIcon />, adminOnly: false },
  { label: 'Config', href: '/config', icon: <SettingsIcon />, adminOnly: true },
]

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const { data: me } = useSWR<AuthUser>(`${BASE}/auth/me`, fetcher)

  const visibleItems = NAV_ITEMS.filter((item) => !item.adminOnly || me?.is_admin)

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar
        position="fixed"
        sx={{ zIndex: (t) => t.zIndex.drawer + 1, bgcolor: 'background.paper' }}
        elevation={0}
      >
        <Toolbar sx={{ justifyContent: 'space-between' }}>
          <Typography variant="h6" fontWeight={700} color="primary.main">
            🎬 CuteVideo Agent
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {me?.plan_slug && <Chip size="small" label={me.plan_slug} />}
            {me?.email && (
              <Typography variant="body2" color="text.secondary">
                {me.email}
              </Typography>
            )}
            <Button
              size="small"
              onClick={() => {
                clearAuthToken()
                router.push('/login')
              }}
            >
              Déconnexion
            </Button>
          </Box>
        </Toolbar>
      </AppBar>

      <Drawer
        variant="permanent"
        sx={{
          width: DRAWER_WIDTH,
          flexShrink: 0,
          '& .MuiDrawer-paper': {
            width: DRAWER_WIDTH,
            boxSizing: 'border-box',
            bgcolor: 'background.paper',
            borderRight: '1px solid rgba(255,255,255,0.08)',
          },
        }}
      >
        <Toolbar />
        <List dense sx={{ pt: 2 }}>
          {visibleItems.map((item) => (
            <ListItemButton
              key={item.href}
              component={Link}
              href={item.href}
              selected={pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href))}
              sx={{
                mx: 1,
                borderRadius: 2,
                mb: 0.5,
                '&.Mui-selected': {
                  bgcolor: 'primary.dark',
                  '&:hover': { bgcolor: 'primary.dark' },
                },
              }}
            >
              <ListItemIcon sx={{ minWidth: 36, color: 'inherit' }}>{item.icon}</ListItemIcon>
              <ListItemText primary={item.label} />
            </ListItemButton>
          ))}
        </List>
      </Drawer>

      <Box component="main" sx={{ flexGrow: 1, p: 3 }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  )
}
