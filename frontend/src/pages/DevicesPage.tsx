import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useAppStore } from '@/store/app'
import { useT } from '@/i18n'
import { Card, CardTitle, Button, Input, Badge, Blob, Status } from '@/components/ui'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'
import { DevicesAPI } from '@/api/devices'
import { deviceManager } from '@/services/smart-cube'
import { Bluetooth, Plus, Trash2, Edit3, Check, X, AlertTriangle, Battery, Cpu, Radio } from 'lucide-react'

type Brand = 'gan' | 'moyu' | 'qiyi' | 'gocube' | 'giiker' | 'manual'

const BRANDS: Array<{ key: Brand; label: string; emoji: string; supports_mac: boolean }> = [
  { key: 'gan',    label: 'GAN (GAN356 / i3 / iCarry / 13 / AiCube)', emoji: '🌿', supports_mac: true  },
  { key: 'moyu',   label: 'MoYu (魔域 RS3M / MFJS / WRM / MHC)',       emoji: '🟧', supports_mac: true  },
  { key: 'qiyi',   label: 'QiYi (Qidi / XMD Tornado V4 / MoFangGe)',   emoji: '🟦', supports_mac: true  },
  { key: 'gocube', label: 'GoCube (BT / Edge / Rubik\'s Connected)',   emoji: '⬛', supports_mac: true  },
  { key: 'giiker', label: 'Giiker (i3S / SuperMem / 小米智能魔方)',     emoji: '🟨', supports_mac: true  },
  { key: 'manual', label: '模拟器 (无硬件)',                            emoji: '🎲', supports_mac: false },
]

const PROTOCOL_BY_BRAND: Record<Brand, string> = {
  gan: 'gan_v4', moyu: 'moyu', qiyi: 'qiyi', gocube: 'gocube', giiker: 'giiker', manual: 'manual',
}

export default function DevicesPage() {
  const user = useAppStore(s => s.user)!
  const nav = useNavigate()
  const qc = useQueryClient()
  const { t } = useT()
  useWebSocketEvents({ userId: user.id }, {})

  const { data: devices, isLoading } = useQuery({
    queryKey: ['devices', user.id],
    queryFn: () => DevicesAPI.list(user.id),
    refetchInterval: 5000,
  })

  const [showPair, setShowPair] = useState(false)
  const [editing, setEditing] = useState<number | null>(null)

  const onDelete = async (id: number) => {
    if (!confirm(t('dev.unpair_confirm'))) return
    await DevicesAPI.delete(user.id, id)
    qc.invalidateQueries({ queryKey: ['devices', user.id] })
  }

  const onConnect = async (id: number) => {
    await DevicesAPI.connect(user.id, id)
    qc.invalidateQueries({ queryKey: ['devices', user.id] })
  }

  // 给 openBluetoothScan 用的回调 (走 deviceManager 扫到设备后, 让 React 重新拉列表)
  const onPaired = () => {
    qc.invalidateQueries({ queryKey: ['devices', user.id] })
  }

  return (
    <div className="space-y-6">
      <div className="text-center relative">
        <Blob color="moss" className="!opacity-15 -top-10 left-1/3 w-72 h-72 animate-breathe" />
        <Badge variant="clay" icon={Bluetooth}>{t('dev.header')}</Badge>
        <h1 className="mt-4 font-serif text-3xl md:text-4xl text-foreground text-balance">
          {t('dev.pair_card_title')}
        </h1>
        <p className="text-muted-foreground mt-2 max-w-xl mx-auto text-balance">
          {t('dev.subtitle')}
        </p>
      </div>

      {/* 已配对设备 */}
      <Card asym={1}>
        <div className="flex items-center justify-between mb-4">
          <CardTitle icon={Cpu}>{t('dev.your_devices')}</CardTitle>
          <div className="flex gap-2">
            <Button variant="outline" onClick={async () => { const ok = await openBluetoothScan(); if (ok) onPaired() }}>
              <Radio size={16} /> {t('dev.scan_bluetooth')}
            </Button>
            <Button variant="primary" onClick={() => setShowPair(!showPair)}>
              {showPair ? <><X size={16} /> {t('dev.cancel')}</> : <><Plus size={16} /> {t('dev.pair_new')}</>}
            </Button>
          </div>
        </div>

        {isLoading && <div className="text-center text-muted-foreground py-6">{t('dev.loading')}</div>}

        {devices && devices.length === 0 && !showPair && (
          <div className="text-center py-12">
            <div className="inline-flex items-center justify-center h-20 w-20 rounded-full bg-muted/60 mb-4">
              <Bluetooth size={32} className="text-muted-foreground" />
            </div>
            <p className="text-muted-foreground mb-4">{t('dev.no_devices')}</p>
            <div className="flex gap-2 justify-center">
              <Button variant="outline" onClick={async () => { const ok = await openBluetoothScan(); if (ok) onPaired() }}>
                <Radio size={16} /> {t('dev.scan_bluetooth')}
              </Button>
              <Button variant="primary" onClick={() => setShowPair(true)}>
                <Plus size={16} /> {t('dev.pair_first')}
              </Button>
            </div>
          </div>
        )}

        <div className="space-y-3">
          {devices?.map(d => (
            <DeviceRow key={d.id} d={d} editing={editing === d.id}
                       onEdit={() => setEditing(d.id)}
                       onSaveEdit={async (nick: string) => { await DevicesAPI.update(user.id, d.id, { nickname: nick }); setEditing(null); qc.invalidateQueries({ queryKey: ['devices', user.id] }) }}
                       onCancelEdit={() => setEditing(null)}
                       onConnect={() => onConnect(d.id)}
                       onDelete={() => onDelete(d.id)}
                       onStartSolve={() => nav('/timer')}
                       t={t} />
          ))}
        </div>
      </Card>

      {showPair && (
        <PairCard onClose={() => setShowPair(false)}
                  onPaired={() => { setShowPair(false); qc.invalidateQueries({ queryKey: ['devices', user.id] }) }}
                  userId={user.id} t={t} />
      )}

      {/* 怎么找 MAC */}
      <Card asym={3} className="p-6">
        <CardTitle icon={AlertTriangle} accent="clay">{t('dev.how_mac_title')}</CardTitle>
        <ol className="text-sm text-foreground/80 space-y-2 list-decimal pl-6">
          <li>{t('dev.how_mac_li1')}</li>
          <li>{t('dev.how_mac_li2')}</li>
          <li>{t('dev.how_mac_li3')}</li>
          <li>{t('dev.how_mac_li4')}</li>
          <li>{t('dev.how_mac_li5')}</li>
        </ol>
      </Card>
    </div>
  )
}

/**
 * BLE 扫描入口: 走 deviceManager.scanAndConnect
 *   1. 弹系统蓝牙选择窗
 *   2. 用户选完设备后, 遍历 deviceManager 内部所有已注册 adapter 的 namePrefix
 *   3. 自动匹配品牌 (GAN / MoYu / QiYi / GoCube / Giiker)
 *   4. 实例化 adapter, 连接 GATT, 订阅事件
 *   5. 适配器事件通过 registerCubeBridge 桥接到 cubeStore
 */
export async function openBluetoothScan(): Promise<boolean> {
  if (!('bluetooth' in navigator)) {
    alert('当前浏览器不支持 Web Bluetooth, 请用 Chrome / Edge')
    return false
  }
  try {
    await deviceManager.scanAndConnect()
    return true
  } catch (e: any) {
    // 用户取消选设备, 或匹配失败
    console.warn('[BLE scan] cancelled or failed:', e?.message || e)
    return false
  }
}

// ── 设备行 ──────────────────────────────────────────
function DeviceRow({ d, editing, onEdit, onSaveEdit, onCancelEdit,
                    onConnect, onDelete, onStartSolve, t }: any) {
  const [nick, setNick] = useState(d.nickname || '')
  const status = d.state
  const online = status === 'inspecting' || status === 'solving' || status === 'scrambling'

  return (
    <div className="bg-muted/30 border border-border/30 rounded-2xl p-4 sm:p-5 flex items-center gap-4 hover:shadow-soft transition-all">
      <div className={`h-12 w-12 rounded-2xl flex items-center justify-center text-lg
                      ${d.brand === 'manual' ? 'bg-muted text-muted-foreground'
                                              : 'bg-primary/10 text-primary'}`}>
        {d.brand === 'gan' ? '🌿' : d.brand === 'moyu' ? '🟧' : d.brand === 'qiyi' ? '🟦' :
         d.brand === 'gocube' ? '⬛' : d.brand === 'giiker' ? '🟨' : '🎲'}
      </div>
      <div className="flex-1 min-w-0">
        {editing ? (
          <div className="flex gap-2">
            <Input value={nick} onChange={e => setNick(e.target.value)}
                   placeholder={t('dev.nickname_ph')} className="text-sm" />
            <Button size="sm" onClick={() => onSaveEdit(nick)}><Check size={12} /></Button>
            <Button size="sm" variant="ghost" onClick={onCancelEdit}><X size={12} /></Button>
          </div>
        ) : (
          <>
            <div className="font-medium text-foreground truncate flex items-center gap-2">
              {d.nickname || d.model || d.brand}
              {d.mac_address && <span className="text-xs text-muted-foreground font-mono">{d.mac_address}</span>}
            </div>
            <div className="text-xs text-muted-foreground flex items-center gap-2 mt-1 flex-wrap">
              <Badge variant="stone">{d.brand}</Badge>
              <Badge variant="stone">{d.protocol}</Badge>
              {d.battery_pct != null && <Badge variant="clay" icon={Battery}>{d.battery_pct}%</Badge>}
              <Badge variant={online ? 'success' : 'stone'}>{status}</Badge>
            </div>
          </>
        )}
      </div>
      <div className="flex gap-2 flex-shrink-0">
        {!editing && (
          <>
            {d.brand !== 'manual' && (
              <Button size="sm" variant="outline" onClick={onConnect}>
                <Bluetooth size={12} /> {t('dev.connect')}
              </Button>
            )}
            {d.brand === 'manual' && (
              <Button size="sm" variant="primary" onClick={onStartSolve}>
                {t('dev.start')}
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onEdit}><Edit3 size={12} /></Button>
            <Button size="sm" variant="ghost" onClick={onDelete}><Trash2 size={12} /></Button>
          </>
        )}
      </div>
    </div>
  )
}

// ── 配对卡片 ────────────────────────────────────────
function PairCard({ onClose, onPaired, userId, t }: { onClose: () => void; onPaired: () => void; userId: number; t: (k: string) => string }) {
  const [brand, setBrand] = useState<Brand>('gan')
  const [mac, setMac] = useState('')
  const [model, setModel] = useState('')
  const [nickname, setNickname] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const submit = async () => {
    setErr(null)
    setSubmitting(true)
    try {
      const req: any = {
        brand,
        mac_address: mac.trim() || null,
        model: model.trim() || null,
        nickname: nickname.trim() || null,
        protocol: PROTOCOL_BY_BRAND[brand],
        adapter: 'simulator', // v1 全 simulator (Web Bluetooth 直连走 openBluetoothScan)
      }
      const d = await DevicesAPI.create(userId, req)
      // simulator 设备: 自动 connect 一下, 进 idle 状态
      if (brand === 'manual') {
        await DevicesAPI.connect(userId, d.id)
      }
      onPaired()
    } catch (e: any) {
      setErr(e?.response?.data?.detail?.[0]?.msg || e?.message || t('dev.failed'))
    } finally {
      setSubmitting(false)
    }
  }

  const currentBrand = BRANDS.find(b => b.key === brand)!

  return (
    <Card asym={2} className="p-6 relative">
      <CardTitle icon={Plus}>{t('dev.pair_card_title')}</CardTitle>

      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3 mb-6">
        {BRANDS.map(b => (
          <button key={b.key} onClick={() => setBrand(b.key)}
                  className={`p-3 rounded-2xl border-2 text-left transition-all
                              ${brand === b.key ? 'border-primary bg-primary/5 shadow-soft' : 'border-border/40 hover:border-primary/40'}`}>
            <div className="text-2xl mb-1">{b.emoji}</div>
            <div className="text-sm font-semibold text-foreground">{b.label}</div>
            {b.key === 'manual' && (
              <div className="text-[10px] text-muted-foreground mt-1">{t('dev.manual_hint')}</div>
            )}
          </button>
        ))}
      </div>

      <div className="space-y-3">
        {currentBrand.supports_mac && (
          <div>
            <label className="text-xs uppercase tracking-wider text-muted-foreground font-semibold pl-1">
              {t('dev.mac_label')}
            </label>
            <Input
              value={mac}
              onChange={e => setMac(e.target.value)}
              placeholder={t('dev.mac_placeholder')}
              className="mt-1 font-mono"
            />
            <p className="text-[11px] text-muted-foreground mt-1 pl-1">
              {t('dev.mac_hint').replace('{brand}', currentBrand.label.split(' ')[0])}
            </p>
          </div>
        )}

        <div className="grid sm:grid-cols-2 gap-3">
          <div>
            <label className="text-xs uppercase tracking-wider text-muted-foreground font-semibold pl-1">{t('dev.model')}</label>
            <Input value={model} onChange={e => setModel(e.target.value)} placeholder={t('dev.model_ph')} className="mt-1" />
          </div>
          <div>
            <label className="text-xs uppercase tracking-wider text-muted-foreground font-semibold pl-1">{t('dev.nickname')}</label>
            <Input value={nickname} onChange={e => setNickname(e.target.value)} placeholder={t('dev.nickname_ph')} className="mt-1" />
          </div>
        </div>
      </div>

      {err && (
        <div className="mt-4 text-sm text-destructive bg-destructive/10 px-4 py-2 rounded-full">
          {err}
        </div>
      )}

      <div className="mt-6 flex gap-3 justify-end">
        <Button variant="ghost" onClick={onClose}>{t('dev.cancel')}</Button>
        <Button variant="primary" onClick={submit} disabled={submitting}>
          {submitting ? t('dev.pairing') : t('dev.pair')}
        </Button>
      </div>
    </Card>
  )
}
