'use client'

import { useState } from 'react'
import AppBar from '@mui/material/AppBar'
import Avatar from '@mui/material/Avatar'
import Box from '@mui/material/Box'
import Chip from '@mui/material/Chip'
import Divider from '@mui/material/Divider'
import Drawer from '@mui/material/Drawer'
import IconButton from '@mui/material/IconButton'
import List from '@mui/material/List'
import ListItemButton from '@mui/material/ListItemButton'
import ListItemIcon from '@mui/material/ListItemIcon'
import ListItemText from '@mui/material/ListItemText'
import ListSubheader from '@mui/material/ListSubheader'
import Menu from '@mui/material/Menu'
import MenuItem from '@mui/material/MenuItem'
import Toolbar from '@mui/material/Toolbar'
import Typography from '@mui/material/Typography'
import useMediaQuery from '@mui/material/useMediaQuery'
import { useTheme } from '@mui/material/styles'
import HomeIcon from '@mui/icons-material/Home'
import VideoLibraryIcon from '@mui/icons-material/VideoLibrary'
import TvIcon from '@mui/icons-material/Tv'
import SmartToyIcon from '@mui/icons-material/SmartToy'
import BarChartIcon from '@mui/icons-material/BarChart'
import SearchIcon from '@mui/icons-material/Search'
import SettingsIcon from '@mui/icons-material/Settings'
import ScheduleIcon from '@mui/icons-material/Schedule'
import AddCircleIcon from '@mui/icons-material/AddCircle'
import KeyIcon from '@mui/icons-material/Key'
import PersonIcon from '@mui/icons-material/Person'
import LogoutIcon from '@mui/icons-material/Logout'
import MenuIcon from '@mui/icons-material/Menu'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import useSWR from 'swr'
import { ThemeToggle } from '@/components/layout'
import { clearAuthToken, fetcher, type AuthUser } from '@/lib/api'

const DRAWER_WIDTH = 240
const BASE = '/api/v1'

type NavSectionId = 'principal' | 'contenu' | 'insights' | 'agents' | 'administration'

interface NavItem {
  label: string
  href: string
  icon: React.ReactNode
  adminOnly?: boolean
  highlight?: boolean
}

interface NavSection {
  id: NavSectionId
  label: string
  adminOnly?: boolean
  items: NavItem[]
}

const NAV_SECTIONS: NavSection[] = [
  {
    id: 'principal',
    label: 'Principal',
    items: [{ label: 'Accueil', href: '/', icon: <HomeIcon fontSize="small" /> }],
  },
  {
    id: 'contenu',
    label: 'Contenu',
    items: [
      { label: 'Créer une vidéo', href: '/create', icon: <AddCircleIcon fontSize="small" />, highlight: true },
      { label: 'Projets', href: '/projects', icon: <VideoLibraryIcon fontSize="small" /> },
      { label: 'Chaînes', href: '/channels', icon: <TvIcon fontSize="small" /> },
    ],
  },
  {
    id: 'insights',
    label: 'Performance',
    items: [{ label: 'Analytics', href: '/analytics', icon: <BarChartIcon fontSize="small" /> }],
  },
  {
    id: 'agents',
    label: 'Agents',
    items: [{ label: 'Monitoring & LLM', href: '/agents', icon: <SmartToyIcon fontSize="small" /> }],
  },
  {
    id: 'administration',
    label: 'Administration',
    adminOnly: true,
    items: [
      { label: 'Marchés analysés', href: '/markets', icon: <SearchIcon fontSize="small" />, adminOnly: true },
      { label: 'Scheduler', href: '/scheduler', icon: <ScheduleIcon fontSize="small" />, adminOnly: true },
      { label: 'Configuration', href: '/config', icon: <SettingsIcon fontSize="small" />, adminOnly: true },
    ],
  },
]

function isNavItemActive(pathname: string, href: string): boolean {
  if (href === '/') return pathname === '/'
  return pathname === href || pathname.startsWith(`${href}/`)
}

function isItemVisible(item: NavItem, isAdmin: boolean): boolean {
  return !item.adminOnly || isAdmin
}

function isSectionVisible(section: NavSection, isAdmin: boolean): boolean {
  if (section.adminOnly && !isAdmin) return false
  return section.items.some((item) => isItemVisible(item, isAdmin))
}

function userInitials(me: AuthUser | undefined): string {
  if (!me) return '?'
  const source = me.display_name?.trim() || me.email
  const parts = source.split(/\s+/).filter(Boolean)
  if (parts.length >= 2) {
    return `${parts[0][0]}${parts[1][0]}`.toUpperCase()
  }
  return source.slice(0, 2).toUpperCase()
}

function NavContent({
  pathname,
  isAdmin,
  onNavigate,
}: {
  pathname: string
  isAdmin: boolean
  onNavigate?: () => void
}) {
  return (
    <Box sx={{ overflow: 'auto', py: 1 }}>
      {NAV_SECTIONS.filter((section) => isSectionVisible(section, isAdmin)).map((section, index) => {
        const visibleItems = section.items.filter((item) => isItemVisible(item, isAdmin))
        return (
          <Box key={section.id}>
            {index > 0 && <Divider sx={{ my: 1, mx: 2 }} />}
            <List
              dense
              subheader={
                <ListSubheader
                  component="div"
                  sx={{
                    bgcolor: 'transparent',
                    lineHeight: '28px',
                    fontSize: 11,
                    fontWeight: 700,
                    letterSpacing: '0.08em',
                    textTransform: 'uppercase',
                    color: 'text.secondary',
                    px: 2,
                  }}
                >
                  {section.label}
                </ListSubheader>
              }
            >
              {visibleItems.map((item) => {
                const selected = isNavItemActive(pathname, item.href)
                return (
                  <ListItemButton
                    key={item.href}
                    component={Link}
                    href={item.href}
                    selected={selected}
                    onClick={onNavigate}
                    sx={{
                      mx: 1,
                      borderRadius: 1.5,
                      mb: 0.25,
                      ...(item.highlight && {
                        bgcolor: selected ? 'primary.dark' : 'primary.main',
                        color: 'primary.contrastText',
                        '&:hover': {
                          bgcolor: 'primary.dark',
                        },
                        '&.Mui-selected': {
                          bgcolor: 'primary.dark',
                          color: 'primary.contrastText',
                          '&:hover': { bgcolor: 'primary.dark' },
                        },
                        '& .MuiListItemIcon-root': { color: 'inherit' },
                      }),
                      ...(!item.highlight && {
                        '&.Mui-selected': {
                          bgcolor: 'action.selected',
                          '&:hover': { bgcolor: 'action.selected' },
                        },
                      }),
                    }}
                  >
                    <ListItemIcon
                      sx={{
                        minWidth: 36,
                        color: item.highlight ? 'inherit' : selected ? 'primary.main' : 'text.secondary',
                      }}
                    >
                      {item.icon}
                    </ListItemIcon>
                    <ListItemText
                      primary={item.label}
                      primaryTypographyProps={{
                        fontSize: 14,
                        fontWeight: item.highlight || selected ? 600 : 400,
                      }}
                    />
                  </ListItemButton>
                )
              })}
            </List>
          </Box>
        )
      })}
    </Box>
  )
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname()
  const router = useRouter()
  const theme = useTheme()
  const isDesktop = useMediaQuery(theme.breakpoints.up('md'))
  const { data: me } = useSWR<AuthUser>(`${BASE}/auth/me`, fetcher)
  const [userMenuAnchor, setUserMenuAnchor] = useState<null | HTMLElement>(null)
  const [mobileOpen, setMobileOpen] = useState(false)

  const isAdmin = me?.is_admin === true
  const userMenuOpen = Boolean(userMenuAnchor)

  const handleLogout = () => {
    setUserMenuAnchor(null)
    clearAuthToken()
    router.push('/login')
  }

  const drawerPaperSx = {
    width: DRAWER_WIDTH,
    boxSizing: 'border-box' as const,
    bgcolor: 'background.paper',
    borderRight: '1px solid',
    borderColor: 'divider',
  }

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh' }}>
      <AppBar
        position="fixed"
        sx={{
          zIndex: (t) => t.zIndex.drawer + 1,
          bgcolor: 'background.paper',
          borderBottom: '1px solid',
          borderColor: 'divider',
        }}
        elevation={0}
      >
        <Toolbar sx={{ justifyContent: 'space-between', gap: 2 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, minWidth: 0 }}>
            {!isDesktop && (
              <IconButton
                edge="start"
                aria-label="Ouvrir le menu"
                onClick={() => setMobileOpen(true)}
                sx={{ mr: 0.5 }}
              >
                <MenuIcon />
              </IconButton>
            )}
            <Typography variant="h6" fontWeight={700} color="primary.main" noWrap>
              CuteVideo Agent
            </Typography>
          </Box>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
            {me?.plan_slug && <Chip size="small" label={me.plan_slug} variant="outlined" />}
            <ThemeToggle />
            <IconButton
              size="small"
              onClick={(e) => setUserMenuAnchor(e.currentTarget)}
              aria-label="Menu utilisateur"
              aria-controls={userMenuOpen ? 'user-menu' : undefined}
              aria-haspopup="true"
              aria-expanded={userMenuOpen ? 'true' : undefined}
            >
              <Avatar sx={{ width: 32, height: 32, fontSize: 14, bgcolor: 'primary.main' }}>
                {userInitials(me)}
              </Avatar>
            </IconButton>
            <Menu
              id="user-menu"
              anchorEl={userMenuAnchor}
              open={userMenuOpen}
              onClose={() => setUserMenuAnchor(null)}
              anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
              transformOrigin={{ vertical: 'top', horizontal: 'right' }}
            >
              {me?.email && (
                <Box sx={{ px: 2, py: 1, maxWidth: 260 }}>
                  <Typography variant="subtitle2" noWrap>
                    {me.display_name || me.email.split('@')[0]}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" noWrap display="block">
                    {me.email}
                  </Typography>
                </Box>
              )}
              <Divider />
              <MenuItem component={Link} href="/account" onClick={() => setUserMenuAnchor(null)}>
                <ListItemIcon>
                  <PersonIcon fontSize="small" />
                </ListItemIcon>
                Mon compte
              </MenuItem>
              <MenuItem component={Link} href="/account/api-keys" onClick={() => setUserMenuAnchor(null)}>
                <ListItemIcon>
                  <KeyIcon fontSize="small" />
                </ListItemIcon>
                Clés API
              </MenuItem>
              <Divider />
              <MenuItem onClick={handleLogout}>
                <ListItemIcon>
                  <LogoutIcon fontSize="small" />
                </ListItemIcon>
                Déconnexion
              </MenuItem>
            </Menu>
          </Box>
        </Toolbar>
      </AppBar>

      <Box component="nav" aria-label="Navigation principale">
        {isDesktop ? (
          <Drawer variant="permanent" sx={{ width: DRAWER_WIDTH, flexShrink: 0, '& .MuiDrawer-paper': drawerPaperSx }}>
            <Toolbar />
            <NavContent pathname={pathname} isAdmin={isAdmin} />
          </Drawer>
        ) : (
          <Drawer
            variant="temporary"
            open={mobileOpen}
            onClose={() => setMobileOpen(false)}
            ModalProps={{ keepMounted: true }}
            sx={{ '& .MuiDrawer-paper': drawerPaperSx }}
          >
            <Toolbar />
            <NavContent pathname={pathname} isAdmin={isAdmin} onNavigate={() => setMobileOpen(false)} />
          </Drawer>
        )}
      </Box>

      <Box component="main" sx={{ flexGrow: 1, p: { xs: 2, md: 3 }, minWidth: 0 }}>
        <Toolbar />
        {children}
      </Box>
    </Box>
  )
}
