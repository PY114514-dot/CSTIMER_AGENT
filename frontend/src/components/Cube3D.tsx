/**
 * Cube3D.tsx ── 真实 WebGL 魔方 (react-three-fiber) 生产级版本
 *
 * 主要设计:
 *  1. 26 个实心 Cubie, 内层黑色塑料, 外层 6 面 WCA 颜色
 *  2. Pivot 转动引擎 + Action Queue
 *  3. 【进阶-6】动态队列调速 (Dynamic Animation Catch-up):
 *       - queue.length <= 1:  标准动画 (150ms / 步)
 *       - queue.length 2~3:   加速 (50ms / 步)
 *       - queue.length > 3:   跳过补间, 直接 snap 到目标 (catch-up)
 *       - 物理魔方 0.5s 内连拨也不会让前端落后
 *  4. 【关键】60Hz 高频数据 (cube_posture / realtime_move) 完全走 ref, React 0 渲染
 *  5. 【进阶-7】外部消费方使用 selector: useSmartCubeBattery() 等,
 *     避免不相关字段变化触发整个组件树重渲染 (渲染雪崩)
 */
import {
  forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState,
} from 'react'
import { Canvas, useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { RoomEnvironment } from 'three/examples/jsm/environments/RoomEnvironment.js'
import { useCubeStore } from '@/store/cubeStore'

// ─── WCA 标准 6 色 (略微提亮, 避免 <Environment preset="studio"> HDR 反射后显得发灰) ──────
const FACE_COLORS: Record<string, string> = {
  U: '#FFFFFF',  // 上 白
  R: '#E63946',  // 右 红 (WCA 官方 C41E3A, 提亮到 E63946 在 HDR 反射下更饱满)
  F: '#06D6A0',  // 前 绿 (WCA 009E60, 提亮到 06D6A0)
  D: '#FFE600',  // 下 黄 (WCA FFD500, 提亮到 FFE600)
  L: '#F77F00',  // 左 橙 (WCA FF5900, 提亮到 F77F00)
  B: '#1E88E5',  // 后 蓝 (WCA 0051BA, 提亮到 1E88E5)
}

const CUBIE_SIZE = 0.96        // 留出 0.04 gap
const CUBIE_HALF = CUBIE_SIZE / 2
const ANIM_STANDARD_MS = 150   // 单步动画 (队列短时, 视觉舒服)
const ANIM_FAST_MS     = 50    // 加速
const STAGGER_THRESHOLD = 1    // queue.length > 1 进入快速段
const SKIP_THRESHOLD   = 3    // queue.length > 3 直接 snap (catch-up)
const MAX_LAG_MS       = 500  // 物理魔方落后阈值

// ─── 共享的 cubie 12 条棱线 BufferGeometry ─────────────
// 26 个 cubie 全部复用这一份几何体 (避免 <Edges> / EdgesGeometry 重建可能带来的"对角线" bug)
// 立方体 8 个顶点 + 12 条棱 -> 24 个 line-segment 端点
const CUBIE_EDGES_GEOMETRY = (() => {
  const h = CUBIE_HALF
  const v = [
    [-h, -h, -h], [ h, -h, -h], [ h,  h, -h], [-h,  h, -h],
    [-h, -h,  h], [ h, -h,  h], [ h,  h,  h], [-h,  h,  h],
  ]
  // 立方体 12 条棱的端点对
  const e = [
    [0,1],[1,2],[2,3],[3,0],  // 底面 z=-h
    [4,5],[5,6],[6,7],[7,4],  // 顶面 z=+h
    [0,4],[1,5],[2,6],[3,7],  // 立柱
  ]
  const arr = new Float32Array(e.length * 2 * 3)
  let p = 0
  for (const [a, b] of e) {
    arr[p++] = v[a][0]; arr[p++] = v[a][1]; arr[p++] = v[a][2]
    arr[p++] = v[b][0]; arr[p++] = v[b][1]; arr[p++] = v[b][2]
  }
  const g = new THREE.BufferGeometry()
  g.setAttribute('position', new THREE.BufferAttribute(arr, 3))
  return g
})()

// ─── 54 字符 Kociemba Facelet 布局 (与后端 SOLVED_FACELET 一致) ─────
//   index  0-8 : U (上)
//   index  9-17: R (右)
//   index 18-26: F (前)
//   index 27-35: D (下)
//   index 36-44: L (左)
//   index 45-53: B (后)
//
//   单面 9 个贴纸的展开顺序 (从左到右, 从上到下):
//   ┌───┬───┬───┐
//   │ 0 │ 1 │ 2 │  ← row=0 (y=+1)
//   ├───┼───┼───┤
//   │ 3 │ 4 │ 5 │  ← row=1 (y= 0)
//   ├───┼───┼───┤
//   │ 6 │ 7 │ 8 │  ← row=2 (y=-1)
//   └───┴───┴───┘
//     ↑   ↑   ↑
//   x=-1 x=0 x=+1   ← col = x + 1
const SOLVED_FACELET = 'UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB'

// 6 个 face 在 facelet 字符串中的起始 index
const FACELET_BASE: Record<string, number> = {
  U: 0, R: 9, F: 18, D: 27, L: 36, B: 45,
}

/**
 * 【核心映射】根据 cubie 坐标 + materialIndex 查 facelet 字符串, 返回该贴纸的颜色字符
 *
 * Three.js BoxGeometry 默认面索引:
 *   0: +X (Right)   1: -X (Left)
 *   2: +Y (Top)     3: -Y (Bottom)
 *   4: +Z (Front)   5: -Z (Back)
 *
 * @param facelet  54 字符状态串
 * @param x,y,z    cubie 坐标 ∈ {-1, 0, 1}
 * @param matIdx   BoxGeometry 面索引 0..5
 * @returns        颜色字符 'U'/'R'/'F'/'D'/'L'/'B', 内部面返回 null (涂黑)
 */
function getCubieFaceColor(
  facelet: string,
  x: number, y: number, z: number,
  matIdx: number,
): string | null {
  // 内部面 (朝向魔方中心的那一面) 永远不贴颜色
  // 判断方法: 该 cubie 坐标中, 与该面法线同向的那个分量 == 0, 即该面是隐藏面
  switch (matIdx) {
    case 0: {  // +X (Right)
      if (x !==  1) return null
      // R 面: 朝向 +X 看过去, 屏幕是 (-Z) 在左, (+Z) 在右
      // col = -(z) + 1 = -z + 1,  row = 1 - y
      const col = -z + 1
      const row =  1 - y
      return facelet[FACELET_BASE.R + row * 3 + col] ?? null
    }
    case 1: {  // -X (Left)
      if (x !== -1) return null
      // L 面: 朝向 -X 看过去, 屏幕是 (+Z) 在左, (-Z) 在右 (镜像)
      // col = z + 1,  row = 1 - y
      const col = z + 1
      const row = 1 - y
      return facelet[FACELET_BASE.L + row * 3 + col] ?? null
    }
    case 2: {  // +Y (Up)
      if (y !==  1) return null
      // U 面: 朝向 +Y (从上往下看), 屏幕是 (-X) 在左, (+X) 在右
      // Z 轴方向: 屏幕 +Y 行 = 后 (-Z) 在顶, 前 (+Z) 在底
      // 约定 U 面展开展示时, 后方 (B) 在顶, 前方 (F) 在底 (符合魔方爱好者习惯)
      // col = x + 1,  row = z + 1
      const col = x + 1
      const row = z + 1
      return facelet[FACELET_BASE.U + row * 3 + col] ?? null
    }
    case 3: {  // -Y (Down)
      if (y !== -1) return null
      // D 面: 朝向 -Y (从下往上看), 屏幕是 (-X) 在左, (+X) 在右
      // Z 轴方向: 屏幕 +Y 行 = 前 (+Z) 在顶, 后 (-Z) 在底
      // col = x + 1,  row = 1 - z  (与 U 相反, 因为 D 面是从下方看的镜像)
      const col = x + 1
      const row = 1 - z
      return facelet[FACELET_BASE.D + row * 3 + col] ?? null
    }
    case 4: {  // +Z (Front)
      if (z !==  1) return null
      // F 面: 朝向 +Z (从前往后看), 屏幕是 (-X) 在左, (+X) 在右
      // col = x + 1,  row = 1 - y
      const col = x + 1
      const row = 1 - y
      return facelet[FACELET_BASE.F + row * 3 + col] ?? null
    }
    case 5: {  // -Z (Back)
      if (z !== -1) return null
      // B 面: 朝向 -Z (从后往前看), 屏幕是 (+X) 在左, (-X) 在右 (左右镜像)
      // 屏幕 +Y 行 = 顶 (y=+1) 在顶, 底 (y=-1) 在底
      // col = -x + 1,  row = 1 - y
      const col = -x + 1
      const row =  1 - y
      return facelet[FACELET_BASE.B + row * 3 + col] ?? null
    }
    default:
      return null
  }
}

export interface Cube3DRef {
  applyMove: (move: string) => void
  applyMoves: (moves: string[]) => void
  /** 接收空格分隔的 WCA 转动字符串, 如 "R U R' U'" */
  scramble: (s: string) => void
  reset: () => void
  /** 接收 54 字符 facelet 字符串, 重新计算所有 cubie 贴纸颜色 */
  setFacelet: (f: string) => void
  /** 接收智能魔方实时四元数 (60Hz) - 走 ref, 不触发 React 渲染 */
  setPosture: (q: { x: number; y: number; z: number; w: number }) => void
  pushRealtimeMove: (move: string) => void
  getCubiesSnapshot: () => Array<{ id: string; pos: [number, number, number]; quat: [number, number, number, number] }>
  /** 主动 dispose: 释放 R3F 资源, 防止切页面时 WebGL Context Lost 报错 */
  dispose: () => void
  /** 内部: 由 RotationEngine 调用, 通知外层 queueRef 就绪, 触发 flush fallback */
  _markReady: () => void
}

declare global {
  interface Window {
    __cubeBridge?: {
      setPosture: (q: { x: number; y: number; z: number; w: number }) => void
      pushRealtimeMove: (m: string) => void
    }
    __cubeEnqueue?: (move: string) => void
  }
}

// ─── 转动解析 ─────────────────────────────────────────
type Axis = 'x' | 'y' | 'z'
type Layer = -1 | 0 | 1

function parseMove(move: string): { axis: Axis; layer: Layer; dir: 1 | -1 } | null {
  if (!move) return null
  const face = move[0]
  const prime = move.includes("'")
  const two   = move.includes('2')
  let dir: 1 | -1 = prime ? -1 : 1
  if (two) dir = (dir * -1) as 1 | -1
  switch (face) {
    case 'R': return { axis: 'x', layer:  1, dir }
    case 'L': return { axis: 'x', layer: -1, dir: (dir * -1) as 1 | -1 }
    case 'U': return { axis: 'y', layer:  1, dir }
    case 'D': return { axis: 'y', layer: -1, dir: (dir * -1) as 1 | -1 }
    case 'F': return { axis: 'z', layer:  1, dir }
    case 'B': return { axis: 'z', layer: -1, dir: (dir * -1) as 1 | -1 }
    default:  return null
  }
}

// ─── 26 Cubie 初始位姿 ────────────────────────────────
// buildCubies 已废弃 (旧版本用 Object3D 占位, 改用 callback ref 模式后不再需要)
// 现在 26 个 cubie 完全由 <Cubie> 在 JSX 嵌套循环里渲染, 位置通过 prop 显式传入.
// 保留这个函数仅为向后兼容 / 旧测试参考.
function buildCubies(): THREE.Object3D[] {
  const out: THREE.Object3D[] = []
  let id = 0
  for (let x = -1; x <= 1; x++) {
    for (let y = -1; y <= 1; y++) {
      for (let z = -1; z <= 1; z++) {
        if (x === 0 && y === 0 && z === 0) continue
        const m = new THREE.Object3D()
        m.position.set(x, y, z)
        m.userData.id = `c${id++}`
        m.userData.home = { x, y, z }
        out.push(m)
      }
    }
  }
  return out
}

const _eul = new THREE.Euler()
function snapCubiesToGrid(cubies: THREE.Object3D[]) {
  for (const c of cubies) {
    c.position.set(
      Math.round(c.position.x),
      Math.round(c.position.y),
      Math.round(c.position.z),
    )
    _eul.setFromQuaternion(c.quaternion, 'XYZ')
    _eul.x = Math.round(_eul.x / (Math.PI / 2)) * (Math.PI / 2)
    _eul.y = Math.round(_eul.y / (Math.PI / 2)) * (Math.PI / 2)
    _eul.z = Math.round(_eul.z / (Math.PI / 2)) * (Math.PI / 2)
    c.quaternion.setFromEuler(_eul)
  }
}

// ─── 单个 Cubie 渲染 (6 面 BoxGeometry, 内层纯黑) ─────
//
// Three.js BoxGeometry 默认面索引顺序:
//   0: +X (Right)   1: -X (Left)
//   2: +Y (Top)     3: -Y (Bottom)
//   4: +Z (Front)   5: -Z (Back)
//
// 真实魔方逻辑:
//  - 只有最外层暴露的面才有贴纸颜色 (从 facelet 字符串查)
//  - 其余 5 个面 (含内部) 全部黑色塑料
function Cubie({
  cubieRef,
  home,
  facelet,
}: {
  cubieRef: (g: THREE.Object3D | null) => void
  home: { x: number; y: number; z: number }
  facelet: string
}) {
  // 【核心】根据 home 坐标 + facelet 字符串决定每个面颜色
  // 内部面 getCubieFaceColor 返回 null -> 用黑色塑料
  // 外露面返回 'U'/'R'/... 字符 -> 查 FACE_COLORS 拿 hex
  // 【材质调参 - 崭新 UV 镀膜魔方塑料质感】
  //   roughness=0.25 让表面光滑, 容易产生高光反射 (跟甘/GAN 魔方贴纸一样)
  //   metalness=0.15 给一点金属感, 黑色边缘更深邃, 彩色贴纸更饱和
  //   envMapIntensity 默认 1.0, 配合 <Environment preset="studio"> 让 HDRI 反射上来
  const materials = useMemo(() => {
    const black = new THREE.MeshStandardMaterial({
      color: '#0a0a0a',
      roughness: 0.55,   // 黑色塑料: 略粗糙 (相比彩色面)
      metalness: 0.25,   // 黑色加金属感让缝隙更深邃
    })
    const coloredCache = new Map<string, THREE.MeshStandardMaterial>()
    const colorFor = (ch: string | null) => {
      if (!ch) return black
      const hex = FACE_COLORS[ch] ?? '#888888'
      let m = coloredCache.get(hex)
      if (!m) {
        m = new THREE.MeshStandardMaterial({
          color: hex,
          roughness: 0.25,   // 彩色贴纸: 光滑 (产生高光)
          metalness: 0.12,   // 轻微金属感, 增强色彩饱和
          envMapIntensity: 1.2,  // 加强 HDR 反射贡献
        })
        coloredCache.set(hex, m)
      }
      return m
    }
    return [
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 0)),  // 0: +X
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 1)),  // 1: -X
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 2)),  // 2: +Y
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 3)),  // 3: -Y
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 4)),  // 4: +Z
      colorFor(getCubieFaceColor(facelet, home.x, home.y, home.z, 5)),  // 5: -Z
    ]
  }, [home.x, home.y, home.z, facelet])

  useEffect(() => () => materials.forEach(m => m.dispose()), [materials])

  return (
    // 【渲染结构】<group position={[x,y,z]}>(色块mesh + 12棱lineSegments)
    //   - position 用 JSX prop 显式传入, 避免 R3F ref 隐式覆盖 Object3D.position
    //   - 用 callback ref (而非 MutableRefObject) 让 R3F 把 group 实例注册到 cubiesRef
    //   - callback ref 同时把 home 写到 userData, 让外层 reset() 能找到
    //   - 色块 mesh 走 R3F 标准 6-材质数组写法 (BoxGeometry 默认 6 group 自动对应 6 face)
    //   - 棱线用 <lineSegments> + 共享 BufferGeometry
    <group
      ref={(g) => {
        if (g) {
          g.userData.home = { ...home }
          cubieRef(g)
        } else {
          cubieRef(null)
        }
      }}
      position={[home.x, home.y, home.z]}
    >
      <mesh material={materials}>
        <boxGeometry args={[CUBIE_SIZE, CUBIE_SIZE, CUBIE_SIZE]} />
      </mesh>
      <lineSegments geometry={CUBIE_EDGES_GEOMETRY}>
        <lineBasicMaterial color="#000000" />
      </lineSegments>
    </group>
  )
}

// ─── 动态调速的 Action Queue ──────────────────────────
interface PendingMove {
  axis: Axis
  layer: Layer
  dir: 1 | -1
  /** 该步入队时间 (ms), 用于 catch-up 判定 */
  enqueuedAt: number
  /** 该步的目标动画时长 (ms) - 推入时根据当时 queue.length 决定 */
  duration: number
  t0: number       // 实际开始时间
  pivot: THREE.Group
  /** 是否要跳过补间 (catch-up) */
  snap: boolean
}

function pickAnimDuration(queueLen: number): number {
  if (queueLen <= STAGGER_THRESHOLD) return ANIM_STANDARD_MS
  if (queueLen <= SKIP_THRESHOLD)     return ANIM_FAST_MS
  return 0  // catch-up: 不补间
}

// ── 模块级 fallback buffer ──
// 解决 BLE 推过来的 move 早于 Cube3D mount 的问题:
//   - BLE Adapter 在 TimerPage 调 onScanBluetooth 后立即 connect, 立刻推 move
//   - Cube3D 还没 mount, RotationEngine 的 useEffect 也没注册 __cubeEnqueue
//   - 如果没有 fallback, 这些 move 就丢了
// 流程: BLE move -> 入模块级 buffer; RotationEngine mount 后注册 __cubeEnqueue, 同时 flush buffer
const _pendingMoves: string[] = []
let _registeredEnqueue: ((m: string) => void) | null = null

function RotationEngine({
  cubiesRef,
  postureRef,
  postureEnabled,
  facelet,
}: {
  cubiesRef: React.MutableRefObject<THREE.Object3D[]>
  postureRef: React.MutableRefObject<THREE.Quaternion | null>
  postureEnabled: boolean
  facelet: string
}) {
  const queueRef = useRef<PendingMove[]>([])

  // 暴露推入口子 (useWebSocketEvents 的 bridge + 父组件 ref 都会用)
  // 【Bug 1 修复 - 模块级 fallback】RotationEngine useEffect 还没跑时, 推过来的 move
  // 先入模块级 _pendingMoves, 注册 __cubeEnqueue 时 flush 一次.
  useEffect(() => {
    const enqueueLocal = (move: string) => {
      const p = parseMove(move)
      if (!p) return
      const now = performance.now()
      const duration = pickAnimDuration(queueRef.current.length)
      queueRef.current.push({
        ...p,
        enqueuedAt: now,
        duration,
        t0: 0,
        pivot: new THREE.Group(),
        snap: duration === 0,
      })
    }
    _registeredEnqueue = enqueueLocal
    window.__cubeEnqueue = enqueueLocal
    // 把 RotationEngine mount 之前累积在 _pendingMoves 的 move 全部 flush
    while (_pendingMoves.length) {
      const m = _pendingMoves.shift()!
      enqueueLocal(m)
    }
    return () => {
      delete window.__cubeEnqueue
      if (_registeredEnqueue === enqueueLocal) _registeredEnqueue = null
    }
  }, [])

  const rootRef = useRef<THREE.Group>(null!)

  useFrame((_, dt) => {
    const root = rootRef.current
    if (!root) return

    // 1) 智能魔方实时姿态: 走 ref, 60Hz 不触发 React 渲染
    if (postureEnabled && postureRef.current) {
      root.quaternion.slerp(postureRef.current, Math.min(1, dt * 12))
    }

    // 2) 队列处理 (但 cubies 还没全部 mount 时跳过)
    const cur = queueRef.current[0]
    if (!cur) return
    // cubiesRef 是 callback ref 异步填充, 26 个都到位前不做转动
    if (cubiesRef.current.length < 26) return

    // 【关键】判断 cubie 是否属于被转动的一层, 用 c.position (相对 root) 的当前坐标
    // 而不是 userData.home (初始 home 不会随转动更新).
    // pivot.attach(c) 之后, c.position 会被重算为相对 pivot 的局部坐标;
    // 因为 pivot 在 root 里, rotation = 0, position = 0, 所以 c.position 仍然等于 home
    // 后续的旋转 (pivot.rotation 改变) 不会改 c.position, 但 c.quaternion 会变.
    // 当 attach 回 root 时, c.position 重新计算为 root 局部坐标 = world 坐标.
    const axisCoord = (c: THREE.Object3D, axis: Axis): number => {
      const p = c.position
      return axis === 'x' ? Math.round(p.x) : axis === 'y' ? Math.round(p.y) : Math.round(p.z)
    }

    // ── catch-up 兜底: 如果最旧一步已经等待 > MAX_LAG_MS, 强制 snap 整队 ──
    if (!cur.t0 && (performance.now() - cur.enqueuedAt) > MAX_LAG_MS) {
      // 把整队全部 snap 跳完, 视觉一次追平
      while (queueRef.current.length) {
        const m = queueRef.current[0]!
        // 找到受影响 cubie, 围绕 pivot 直接转 90° (不补间)
        const pivot = m.pivot
        root.add(pivot)
        for (const c of cubiesRef.current) {
          if (axisCoord(c, m.axis) === m.layer) pivot.attach(c)
        }
        ;(pivot.rotation as any)[m.axis] = m.dir * (Math.PI / 2)
        for (const c of [...pivot.children]) root.attach(c)
        snapCubiesToGrid(cubiesRef.current)
        root.remove(pivot)
        queueRef.current.shift()
      }
      return
    }

    if (cur.t0 === 0) {
      // 2.1 受影响的 9 个 cubie attach 到 pivot
      const pivot = cur.pivot
      root.add(pivot)
      for (const c of cubiesRef.current) {
        if (axisCoord(c, cur.axis) === cur.layer) pivot.attach(c)
      }
      cur.t0 = performance.now()
    }

    if (cur.snap) {
      // catch-up: 立即到位
      ;(cur.pivot.rotation as any)[cur.axis] = cur.dir * (Math.PI / 2)
    } else {
      // 2.2 推进旋转 (easeOutCubic)
      const elapsed = performance.now() - cur.t0
      const k = Math.min(1, elapsed / cur.duration)
      const eased = 1 - Math.pow(1 - k, 3)
      const angle = cur.dir * eased * (Math.PI / 2)
      cur.pivot.rotation.set(0, 0, 0)
      ;(cur.pivot.rotation as any)[cur.axis] = angle
      if (k < 1) return  // 还在动画中
    }

    // 2.3 结束: cubie 回归 root, snap 量化, 销毁 pivot
    for (const c of [...cur.pivot.children]) root.attach(c)
    snapCubiesToGrid(cubiesRef.current)
    root.remove(cur.pivot)
    queueRef.current.shift()

    // 在 catch-up 模式下, 一次性把后续队列清掉, 避免下一帧又触发
    if (cur.snap) {
      // 把 queue 后续的 snap 步也快速消化 (直接完成, 不进入 useFrame 排队)
      // 注意: 这里只更新 ref, 不动 React
      while (queueRef.current.length && queueRef.current[0]!.snap) {
        const m = queueRef.current[0]!
        const pivot = m.pivot
        root.add(pivot)
        for (const c of cubiesRef.current) {
          if (axisCoord(c, m.axis) === m.layer) pivot.attach(c)
        }
        ;(pivot.rotation as any)[m.axis] = m.dir * (Math.PI / 2)
        for (const c of [...pivot.children]) root.attach(c)
        snapCubiesToGrid(cubiesRef.current)
        root.remove(pivot)
        queueRef.current.shift()
      }
    }
  })

  return (
    // 【渲染】3x3x3 嵌套循环生成 26 个 cubie (跳过中心), 位置通过 JSX prop 显式传入
    //   - 用 callback ref 让 R3F 把每个 group 实例注册到 cubiesRef 对应 index
    //   - RotationEngine 通过 cubiesRef.current[i] 拿到 group, 配合 pivot.attach 转动
    //   - 这种结构与 buildCubies() 的 index 一一对应, 也保留了 home 信息
    <group ref={rootRef}>
      {(() => {
        const elements: JSX.Element[] = []
        let i = 0
        for (let x = -1; x <= 1; x++) {
          for (let y = -1; y <= 1; y++) {
            for (let z = -1; z <= 1; z++) {
              if (x === 0 && y === 0 && z === 0) continue
              const idx = i++
              const home = { x, y, z }
              elements.push(
                <Cubie
                  key={`cubie-${x}-${y}-${z}`}
                  cubieRef={(g) => {
                    if (g) cubiesRef.current[idx] = g
                  }}
                  home={home}
                  facelet={facelet}
                />
              )
            }
          }
        }
        return elements
      })()}
    </group>
  )
}

// ─── 对外组件 ───────────────────────────────────────
export const Cube3D = forwardRef<Cube3DRef, { size?: number; className?: string; enablePosture?: boolean; initialFacelet?: string }>(
  ({ size = 320, className, enablePosture = true, initialFacelet = SOLVED_FACELET }, ref) => {
    // cubiesRef 初始为 26 个 null 占位; <Cubie> 的 callback ref 会按 index 填充
    // (顺序跟 buildCubies 一样, 也跟 RotationEngine JSX 嵌套循环一样: 0,0,0 跳过, x 最外层)
    const cubiesRef = useRef<THREE.Object3D[]>(new Array(26).fill(null))
    const postureRef = useRef<THREE.Quaternion | null>(null)
    const apiRef = useRef<Cube3DRef | null>(null)
    // facelet 镜像: 写到 ref (给 setFacelet) + 同步到 state (触发 React 渲染材质)
    // 注意: 这不是高频数据, 一秒最多变 1-2 次 (智能魔方每次 scramble / solve 完成), 用 state 安全
    const [facelet, setFaceletState] = useState<string>(initialFacelet)
    const faceletRef = useRef<string>(initialFacelet)
    faceletRef.current = facelet

    // 【Bug 1 修复】订阅 cubeStore.facelet (BLE 真实硬件推过来的)
    // 当 cubeStore 收到 BLE 魔方的 54 字符状态时, 同步到本地 state, 触发 3D 重渲染
    // 这条路与后端 WebSocket cube_move 是独立的:
    //   - cube_move 走 useFrame 入队动画 (高频, 单步 move)
    //   - facelet 走 React state 重新计算材质 (低频, 整盘刷新)
    useEffect(() => {
      // 不在 mount 立即同步 (会覆盖 prop 传入的 initialFacelet),
      // 只在 store 里的 facelet 真实更新时同步
      return useCubeStore.subscribe((state, prev) => {
        if (state.facelet && state.facelet !== prev.facelet && state.facelet !== faceletRef.current) {
          setFaceletState(state.facelet)
        }
      })
    }, [])

    // 【Bug 1 修复 - 模块级 fallback】所有 applyMove/scramble 调用先 push 到模块级 _pendingMoves,
    // RotationEngine 内部 queueRef 注册完成时 (见 useEffect), 自动 flush 所有累积的 move
    useImperativeHandle(ref, () => ({
      /**
       * 标准入队: 走模块级 _pendingMoves -> RotationEngine ready 时 flush
       * 无论 Cube3D 处于什么 mount 阶段, BLE / WS 实时 move 都不会丢失
       */
      applyMove:  (m) => { _pendingMoves.push(m); if (_registeredEnqueue) _registeredEnqueue(m) },
      applyMoves: (moves) => { _pendingMoves.push(...moves); if (_registeredEnqueue) for (const m of moves) _registeredEnqueue(m) },
      scramble:   (s) => { const ms = s.split(/\s+/).filter(Boolean); _pendingMoves.push(...ms); if (_registeredEnqueue) for (const m of ms) _registeredEnqueue(m) },
      reset: () => {
        // 26 个 cubie 重置回 home 位置
        for (const c of cubiesRef.current) {
          if (!c) continue
          const home = c.userData?.home as { x: number; y: number; z: number } | undefined
          if (home) {
            c.position.set(home.x, home.y, home.z)
            c.quaternion.identity()
          }
        }
        setFaceletState(SOLVED_FACELET)
      },
      setFacelet: (f) => {
        if (typeof f !== 'string' || f.length !== 54) return
        faceletRef.current = f
        setFaceletState(f)
      },
      setPosture: (q) => {
        if (!postureRef.current) postureRef.current = new THREE.Quaternion()
        postureRef.current.set(q.x, q.y, q.z, q.w)
      },
      pushRealtimeMove: (m) => { _pendingMoves.push(m); if (_registeredEnqueue) _registeredEnqueue(m) },
      getCubiesSnapshot: () => cubiesRef.current.map(c => ({
        id:   c.userData.id,
        pos:  [c.position.x, c.position.y, c.position.z],
        quat: [c.quaternion.x, c.quaternion.y, c.quaternion.z, c.quaternion.w],
      })),
      dispose: () => {
        delete window.__cubeBridge
        if (window.__cubeBridge) delete (window as any).__cubeBridge
      },
      _markReady: () => { /* no-op; 由 RotationEngine 内部模块级 flush 处理 */ },
    }))

    // 注册桥接: useWebSocketEvents 的高频数据走 window.__cubeBridge
    useEffect(() => {
      window.__cubeBridge = {
        setPosture: (q) => apiRef.current?.setPosture(q),
        pushRealtimeMove: (m) => apiRef.current?.pushRealtimeMove(m),
      }
      return () => { delete window.__cubeBridge }
    }, [])

    return (
      <div className={className} style={{ width: size, height: size }}>
        <Canvas
          // 【Bug 2 修复 - 相机参数】position=[3.2, 3.2, 3.2] 对 cube 整体 (3x3x3) 来说
          // 太近, 加上 maxDistance=10, 用户能滚轮缩到很近导致画面裁切.
          // 修正: distance 5.5 + fov 35 + maxDistance 8, 既保证初始居中, 又限制缩放范围
          camera={{ position: [4.5, 4.0, 5.5], fov: 35, near: 0.1, far: 100 }}
          dpr={[1, 2]}
          gl={{ antialias: true, alpha: true }}
          // 【关键 - 零网络依赖 HDR】用 onCreated 拿 scene/gl 后, 用 Three.js 官方
          // RoomEnvironment + PMREMGenerator 在内存里烘一张"影棚"反射贴图,
          // 直接挂到 scene.environment. 完全不走任何 CDN/HDR 文件, 不会 timeout.
          onCreated={(state) => {
            // 【关键 - 零网络依赖 HDR】用 onCreated 拿 scene/gl 后, 用 Three.js 官方
            // RoomEnvironment + PMREMGenerator 在内存里烘一张"影棚"反射贴图,
            // 直接挂到 scene.environment. 完全不走任何 CDN/HDR 文件, 不会 timeout.
            const gl = state.gl
            const scene = state.scene
            const pmrem = new THREE.PMREMGenerator(gl)
            const env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
            scene.environment = env
          }}
        >
          {/* 【光影系统 v2 - 影棚级渲染 (零网络依赖)】
              1. scene.environment 由 onCreated 注入 RoomEnvironment 烘出的 IBL
                 (Three.js 官方程序化生成, 不依赖任何 HDR 文件)
              2. 4 个 directionalLight 强化多角度高光
              3. ambientLight 1.5 避免背光面纯黑
          */}
          <ambientLight intensity={1.5} />
          {/* Key light: 右上 45° 主光, 产生主高光 */}
          <directionalLight position={[6, 8, 6]} intensity={3.0} color="#ffffff" />
          {/* Fill light: 左下补色, 提亮背光面 */}
          <directionalLight position={[-6, -3, -4]} intensity={1.5} color="#e0e8ff" />
          {/* Top light: 顶部, 增强 U 面白色 */}
          <directionalLight position={[0, 10, 0]} intensity={1.2} color="#ffffff" />
          {/* Back rim light: 后方勾边光, 让彩色面边缘有"金属质感"的勾边 */}
          <directionalLight position={[-3, 3, -8]} intensity={0.8} color="#fff5e0" />
          <RotationEngine
            cubiesRef={cubiesRef}
            postureRef={postureRef as any}
            postureEnabled={enablePosture}
            facelet={facelet}
          />
          {/* 【Bug 2 修复 - OrbitControls】禁用滚轮缩放 (enableZoom=false),
              只保留鼠标拖拽旋转视角, 防止用户误触滚轮导致魔方巨大/裁切.
              minPolarAngle/maxPolarAngle 限制俯仰范围, 防止用户拖到上下完全翻转视角. */}
          <OrbitControls
            enableZoom={false}
            enablePan={false}
            enableDamping
            dampingFactor={0.1}
            minPolarAngle={Math.PI / 6}
            maxPolarAngle={Math.PI * 5 / 6}
            target={[0, 0, 0]}
          />
        </Canvas>
      </div>
    )
  },
)
Cube3D.displayName = 'Cube3D'

/* ────────────────────────────────────────────────────────
 * 【进阶-7】Zustand Selector 用法示例 (注释)
 *
 *  // 错误写法 (渲染雪崩):
 *  const state = useAppStore()                  // 整个 store 变化都触发 re-render
 *  const { user, tasks } = useAppStore(s => s)   // 同样返回整个 state
 *
 *  // 正确写法 (单字段 selector):
 *  const user = useAppStore(s => s.user)         // 只有 user 变化才 re-render
 *  const tasks = useAppStore(s => s.tasks)       // 只有 tasks 变化才 re-render
 *
 *  // 正确写法 (多字段用 useShallow 做浅比较, 避免每次返回新对象导致渲染):
 *  import { useShallow } from 'zustand/react/shallow'
 *  const { status, battery } = useAppStore(
 *    useShallow(s => ({ status: s.smartCube.status, battery: s.smartCube.battery })),
 *  )
 *
 *  // 业务方推荐:
 *  export const useSmartCubeBattery = () => useAppStore(s => s.smartCube.battery)
 *  export const useSmartCubeStatus  = () => useAppStore(s => s.smartCube.status)
 *  export const useUser = () => useAppStore(s => s.user)
 * ──────────────────────────────────────────────────────── */
