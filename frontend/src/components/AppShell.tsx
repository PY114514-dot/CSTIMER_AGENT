import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { useAppStore } from '@/store/app'
import { useT } from '@/i18n'
import { useState } from 'react'
import { LogOut, Languages, Menu, X } from 'lucide-react'
import { clsx } from 'clsx'

export default function AppShell() {
  const user = useAppStore(s => s.user)
  const logout = useAppStore(s => s.logout)
  const nav = useNavigate()
  const { t, getLang, setLang } = useT()
  const [mobileOpen, setMobileOpen] = useState(false)

  const navItems: Array<[string, string]> = [
    ['',         t('nav.dashboard')],
    ['timer',    t('nav.timer')],
    ['training', t('nav.training')],
    ['devices',  t('nav.devices') || 'Devices'],
    ['formulas', t('nav.formulas')],
    ['replay',   t('replay.title')],
    ['agent',    t('nav.agent')],
  ]

  return (
    <div className="min-h-screen relative overflow-x-hidden">
      {/* 背景 blob 装饰 */}
      <div className="fixed -top-32 -left-32 w-[480px] h-[480px] rounded-blob-1 bg-gradient-to-br from-primary/15 to-accent/10 blur-3xl pointer-events-none animate-breathe" />
      <div className="fixed top-1/3 -right-40 w-[520px] h-[520px] rounded-blob-2 bg-gradient-to-br from-secondary/15 to-accent/10 blur-3xl pointer-events-none animate-breathe" style={{ animationDelay: '2s' }} />
      <div className="fixed bottom-0 left-1/3 w-[400px] h-[400px] rounded-blob-3 bg-gradient-to-br from-accent/25 to-muted/15 blur-3xl pointer-events-none animate-breathe" style={{ animationDelay: '4s' }} />

      {/* 浮动 pill nav */}
      <header className="pt-6 px-4 sm:px-6 lg:px-8">
        <nav className="nav-floating max-w-6xl">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-full bg-primary text-white inline-flex items-center justify-center font-serif font-bold text-lg shadow-soft">
              C
            </div>
            <span className="font-serif font-bold text-foreground hidden sm:inline">{t('app.title')}</span>
          </div>

          <div className="hidden md:flex items-center gap-1">
            {navItems.map(([path, label]) => (
              <NavLink key={path} to={`/${path}`} end={path === ''}
                className={({ isActive }) => clsx('nav-pill', isActive && 'nav-pill-active')}>
                {label}
              </NavLink>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setLang(getLang() === 'zh' ? 'en' : 'zh')}
              className="nav-pill"
              title="Toggle language"
            >
              <Languages size={16} className="mr-1" />
              {getLang() === 'zh' ? '中' : 'EN'}
            </button>
            <span className="text-sm text-muted-foreground hidden sm:inline">
              {user?.username}
            </span>
            <button onClick={() => { logout(); nav('/login') }}
                    className="nav-pill hover:text-destructive" title={t('logout')}>
              <LogOut size={16} />
            </button>
            <button className="md:hidden nav-pill" onClick={() => setMobileOpen(!mobileOpen)}>
              {mobileOpen ? <X size={18} /> : <Menu size={18} />}
            </button>
          </div>
        </nav>

        {/* Mobile menu */}
        {mobileOpen && (
          <div className="md:hidden mt-2 mx-auto max-w-6xl card-organic rounded-[2rem] py-3">
            {navItems.map(([path, label]) => (
              <NavLink key={path} to={`/${path}`} end={path === ''}
                onClick={() => setMobileOpen(false)}
                className={({ isActive }) => clsx(
                  'block px-5 py-3 rounded-full text-sm font-medium mx-2',
                  isActive ? 'bg-primary/10 text-primary' : 'text-muted-foreground hover:bg-muted/60'
                )}>
                {label}
              </NavLink>
            ))}
          </div>
        )}
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8 lg:py-12 relative">
        <Outlet />
      </main>
    </div>
  )
}
