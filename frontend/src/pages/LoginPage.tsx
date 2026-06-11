import { useState } from 'react'
import { useAppStore } from '@/store/app'
import { useNavigate } from 'react-router-dom'
import { useT } from '@/i18n'
import { Input, Button, Blob } from '@/components/ui'
import { User2, Sparkles } from 'lucide-react'

export default function LoginPage() {
  const [username, setUsername] = useState('')
  const login = useAppStore(s => s.login)
  const loading = useAppStore(s => s.loading)
  const nav = useNavigate()
  const [err, setErr] = useState<string | null>(null)
  const { t } = useT()

  const submit = async () => {
    if (!username.trim()) { setErr(t('login.error.empty')); return }
    try {
      await login(username.trim())
      nav('/')
    } catch (e: any) {
      setErr(e?.message || t('login.error.empty'))
    }
  }

  return (
    <div className="min-h-screen relative flex items-center justify-center px-4 overflow-hidden">
      {/* 背景装饰 */}
      <Blob color="moss"  className="-top-40 -left-40 w-[600px] h-[600px] animate-breathe" />
      <Blob color="clay"  className="-bottom-40 -right-40 w-[700px] h-[700px] animate-breathe" style={{ animationDelay: '3s' }} />
      <Blob color="sand"  className="top-1/3 left-1/2 w-[400px] h-[400px] animate-breathe" style={{ animationDelay: '5s' }} />

      <div className="relative max-w-md w-full animate-fade-in">
        {/* Logo / 头部 */}
        <div className="text-center mb-8">
          <div className="inline-flex items-center justify-center h-20 w-20 rounded-full bg-primary text-white shadow-float mb-4 animate-breathe">
            <Sparkles size={32} strokeWidth={1.8} />
          </div>
          <h1 className="font-serif text-3xl md:text-4xl text-foreground mb-2">{t('app.title')}</h1>
          <p className="text-muted-foreground text-sm">{t('login.placeholder')}</p>
        </div>

        {/* 登录卡片 */}
        <div className="card-organic card-asym-1 p-8 sm:p-10">
          <div className="space-y-5">
            <div>
              <label className="text-xs uppercase tracking-wider text-muted-foreground font-semibold pl-1">
                {t('login.placeholder')}
              </label>
              <div className="relative mt-2">
                <User2 size={18} className="absolute left-5 top-1/2 -translate-y-1/2 text-muted-foreground pointer-events-none" />
                <Input
                  autoFocus
                  value={username}
                  onChange={e => setUsername(e.target.value)}
                  onKeyDown={e => e.key === 'Enter' && submit()}
                  placeholder={t('login.placeholder')}
                  className="pl-12"
                  data-testid="username-input"
                />
              </div>
            </div>

            {err && (
              <div className="text-sm text-destructive bg-destructive/10 px-4 py-2 rounded-full animate-fade-in">
                {err}
              </div>
            )}

            <Button
              variant="primary"
              size="lg"
              onClick={submit}
              disabled={loading}
              className="w-full"
            >
              {loading ? '...' : t('login.button')}
            </Button>
          </div>

          <p className="text-xs text-center text-muted-foreground mt-6">
            new here? Just type a username to create your account
          </p>
        </div>
      </div>
    </div>
  )
}
