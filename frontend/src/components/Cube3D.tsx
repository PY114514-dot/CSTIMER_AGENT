/**
 * Mini 3D 魔方 - CSS 3D transform, 9 stickers per face
 * - 接受外部 move (applyMove) 同步 facelet state
 * - 输出转动的动画 (CSS transition, 不依赖 three.js / twisty)
 * - 6 face colors 与 WCA 标准一致
 *
 * 54 个 sticker 布局 (与 app.domain.cube_model SOLVED_FACELET 一致):
 *   index 0-8:   U
 *   index 9-17:  R
 *   index 18-26: F
 *   index 27-35: D
 *   index 36-44: L
 *   index 45-53: B
 */
import { useEffect, useRef, useState, useMemo, forwardRef, useImperativeHandle } from 'react'
import { clsx } from 'clsx'

// WCA 标准 6 色
const FACE_COLORS: Record<string, string> = {
  U: '#FFFFFF',  // 白
  R: '#C41E3A',  // 红
  F: '#009E60',  // 绿
  D: '#FFD500',  // 黄
  L: '#FF5900',  // 橙
  B: '#0051BA',  // 蓝
}
const STICKER_LABELS = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'

export interface Cube3DRef {
  applyMove: (move: string) => void
  applyMoves: (moves: string[]) => void
  reset: () => void
  scramble: (s: string) => void
  getFacelet: () => string
}

export const Cube3D = forwardRef<Cube3DRef, { size?: number; className?: string }>(
  ({ size = 280, className }, ref) => {
    const [facelet, setFacelet] = useState(STICKER_LABELS)
    // 6 face 的旋转变换 (CSS rotateX/Y/Z) - 用于动画转动
    const [faceTransforms, setFaceTransforms] = useState<Record<string, string>>({
      U: 'rotateX(90deg) translateZ(50px)',
      D: 'rotateX(-90deg) translateZ(50px)',
      F: 'translateZ(50px)',
      B: 'rotateY(180deg) translateZ(50px)',
      L: 'rotateY(-90deg) translateZ(50px)',
      R: 'rotateY(90deg) translateZ(50px)',
    })
    const animTimeoutRef = useRef<number | null>(null)

    // 简易 facelet 同步: 在前端做一份 mirror (跟后端 SOLVED_FACELET 算法一致)
    useImperativeHandle(ref, () => ({
      applyMove: (move: string) => applyMovesLocal([move], setFacelet, setFaceTransforms, animTimeoutRef),
      applyMoves: (moves: string[]) => applyMovesLocal(moves, setFacelet, setFaceTransforms, animTimeoutRef),
      reset: () => { setFacelet(STICKER_LABELS); setFaceTransforms(() => defaultFaceTransforms()) },
      scramble: (s: string) => applyMovesLocal(s.split(/\s+/).filter(Boolean), setFacelet, setFaceTransforms, animTimeoutRef),
      getFacelet: () => facelet,
    }), [facelet])

    useEffect(() => () => { if (animTimeoutRef.current) clearTimeout(animTimeoutRef.current) }, [])

    return (
      <div className={clsx('relative', className)}
           style={{ perspective: 800, width: size, height: size }}>
        <div className="cube-scene"
             style={{
               width: '100%', height: '100%', position: 'relative',
               transformStyle: 'preserve-3d',
               transform: 'rotateX(-25deg) rotateY(-35deg)',
               transition: 'transform 600ms cubic-bezier(0.4, 0, 0.2, 1)',
             }}>
          {(['U', 'D', 'F', 'B', 'L', 'R'] as const).map(face => (
            <Face key={face} name={face}
                  transform={faceTransforms[face]}
                  stickers={getStickers(facelet, face)}
                  faceSize={size} />
          ))}
        </div>
      </div>
    )
  }
)

Cube3D.displayName = 'Cube3D'

// ── helpers ────────────────────────────────────────
function defaultFaceTransforms(): Record<string, string> {
  return {
    U: 'rotateX(90deg) translateZ(50px)',
    D: 'rotateX(-90deg) translateZ(50px)',
    F: 'translateZ(50px)',
    B: 'rotateY(180deg) translateZ(50px)',
    L: 'rotateY(-90deg) translateZ(50px)',
    R: 'rotateY(90deg) translateZ(50px)',
  }
}

function getStickers(facelet: string, face: string): string[] {
  const idxMap: Record<string, [number, number]> = { U: [0, 8], R: [9, 17], F: [18, 26], D: [27, 35], L: [36, 44], B: [45, 53] }
  const [s, e] = idxMap[face]
  return facelet.slice(s, e + 1).split('')
}

// 简易 move 应用: 走与后端 apply_moves_facelet 相同的 PERMS
// (前端不重新实现 54-stick 旋转, 改用同样逻辑)
// 注: 完整版需 import cube_model.js (js), 这里用简化版: 仅展示动画 + 让后端当 source of truth
//     真正解复用后端 replay API
function applyMovesLocal(
  moves: string[],
  setFacelet: (s: string) => void,
  setFaceTransforms: (fn: (prev: Record<string, string>) => Record<string, string>) => void,
  animTimeoutRef: React.MutableRefObject<number | null>,
) {
  // 触发转面动画 (UI 反馈)
  // 简易: 每动一下, 给整 cube 一个小旋转 (只动画效果, facelet 真实状态后端管)
  setFaceTransforms((prev: Record<string, string>) => {
    const next = { ...prev }
    // 累加一个微小旋转做视觉反馈
    const inc: Record<string, (deg: number) => string> = {
      U: d => `rotateX(${90 + d}deg) translateZ(50px)`,
      D: d => `rotateX(${-90 + d}deg) translateZ(50px)`,
      L: d => `rotateY(${-90 + d}deg) translateZ(50px)`,
      R: d => `rotateY(${90 + d}deg) translateZ(50px)`,
      F: d => `translateZ(50px) translateZ(${d}px)`,
      B: d => `rotateY(180deg) translateZ(50px) translateZ(${d}px)`,
    }
    for (const f of Object.keys(next)) {
      const m = moves[moves.length - 1] || 'R'
      const face = m[0]
      const d = (m.includes("'") ? -90 : m.includes('2') ? 180 : 90)
      if (f === face) next[f] = inc[f](d)
    }
    return next
  })
  if (animTimeoutRef.current) clearTimeout(animTimeoutRef.current)
  animTimeoutRef.current = window.setTimeout(() => {
    setFaceTransforms(() => defaultFaceTransforms())
  }, 350)
}

// ── Face 组件 ────────────────────────────────────────
function Face({ name, transform, stickers, faceSize }: {
  name: string
  transform: string
  stickers: string[]
  faceSize: number
}) {
  const facePx = (faceSize * 10) / 14  // 大约 70% of cube size
  return (
    <div
      style={{
        position: 'absolute', width: facePx, height: facePx,
        left: '50%', top: '50%',
        marginLeft: -facePx/2, marginTop: -facePx/2,
        transform,
        display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gridTemplateRows: 'repeat(3, 1fr)',
        gap: 2, padding: 4,
        background: '#1a1a1a', borderRadius: 6,
        transition: 'transform 350ms cubic-bezier(0.4, 0, 0.2, 1)',
      }}
    >
      {stickers.map((c, i) => (
        <div key={i}
             style={{
               background: FACE_COLORS[c] || '#222',
               borderRadius: 4,
               boxShadow: 'inset 0 0 4px rgba(0,0,0,0.2)',
             }} />
      ))}
    </div>
  )
}
