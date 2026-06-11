/**
 * RTL 单测: AppShell / LoginPage / AgentPage 渲染逻辑
 * - 不连真实后端, 用 vi.mock 替 axios
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

// ── mock 整个 api/client ──────────────────────────────
vi.mock('@/api/client', () => ({
  UsersAPI: {
    create: vi.fn(),
    get: vi.fn(),
    byName: vi.fn(),
  },
  DashboardAPI: {
    today: vi.fn().mockResolvedValue({
      date: '2026-06-10',
      daily_goal: null,
      current_session: null,
      latest_ai_report: null,
      training_tasks: [],
      stage_breakdown: [],
      pause_heatmap: [],
      trend_30: [],
    }),
    recommendGoal: vi.fn(),
  },
  FormulasAPI: {
    sets: vi.fn().mockResolvedValue([
      { id: 1, code: 'PLL', puzzle: '3x3', display_name: 'PLL', case_count: 21, source: 'test', fetched_at: 0 },
    ]),
    set: vi.fn(),
    search: vi.fn().mockResolvedValue([]),
    seed: vi.fn(),
  },
  TrainingAPI: { today: vi.fn().mockResolvedValue([]), markDone: vi.fn(), skip: vi.fn() },
  SessionsAPI: { list: vi.fn().mockResolvedValue([]), get: vi.fn(), close: vi.fn(), aggregate: vi.fn(), generateTraining: vi.fn() },
  SolvesAPI: { start: vi.fn(), addMove: vi.fn(), finish: vi.fn() },
  AIAPI: { analyze: vi.fn(), latest: vi.fn() },
}))

vi.mock('@/api/agent', () => ({
  ai: {
    chat: vi.fn().mockResolvedValue({ answer: 'mock answer', steps: 0, transcript: [] }),
    chatStream: vi.fn().mockImplementation((_uid, _sid, _msg, onEvent) => {
      // 模拟一次性流: tool_start + answer + final
      setTimeout(() => {
        onEvent('tool_start', { tool: 'lookup_formulas', args: {} })
        onEvent('answer', { text: '你最近 PLL 慢' })
        onEvent('final', { answer: '你最近 PLL 慢', steps: 1, transcript: [] })
      }, 0)
      return () => {}
    }),
  },
}))

import { StageStackedBar, PauseHeatmap, TrendLine } from '@/components/Charts'

import { useAppStore } from '@/store/app'
import { UsersAPI, DashboardAPI } from '@/api/client'
import { ai } from '@/api/agent'
import AppShell from '@/components/AppShell'
import LoginPage from '@/pages/LoginPage'
import FormulasPage from '@/pages/FormulasPage'
import AgentPage from '@/pages/AgentPage'
import { useWebSocketEvents } from '@/hooks/useWebSocketEvents'

function renderAt(path: string, ui: React.ReactNode) {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={ui} />
          <Route element={<AppShell />}>
            <Route path="/formulas" element={<FormulasPage />} />
            <Route path="/agent" element={<AgentPage />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  localStorage.clear()
  useAppStore.setState({ user: null, tasks: [] })
  vi.clearAllMocks()
})

describe('LoginPage', () => {
  it('renders empty state', () => {
    renderAt('/login', <div />)
    expect(screen.getByPlaceholderText(/用户名/)).toBeInTheDocument()
    expect(screen.getByText(/进入/)).toBeInTheDocument()
  })

  it('shows error if empty submit', async () => {
    renderAt('/login', <div />)
    await userEvent.click(screen.getByText(/^进入$/))
    expect(await screen.findByText(/请输入用户名/)).toBeInTheDocument()
  })

  it('calls UsersAPI.create on submit and stores user', async () => {
    const fakeUser = { id: 1, username: 'alice', timezone: 'Asia/Shanghai', created_at: 0 }
    vi.mocked(UsersAPI.create).mockResolvedValue(fakeUser)
    renderAt('/login', <div />)
    await userEvent.type(screen.getByPlaceholderText(/用户名/), 'alice')
    await userEvent.click(screen.getByText(/^进入$/))
    await waitFor(() => expect(UsersAPI.create).toHaveBeenCalledWith('alice'))
    expect(JSON.parse(localStorage.getItem('cstimer_user_v1')!)).toEqual(fakeUser)
  })
})

describe('FormulasPage', () => {
  it('renders list of sets from API', async () => {
    useAppStore.setState({
      user: { id: 1, username: 'alice', timezone: 'Asia/Shanghai', created_at: 0 },
    })
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><FormulasPage /></MemoryRouter>
      </QueryClientProvider>
    )
    // 页面同时显示 code (PLL) 和 source (test) -- 至少 1 个 PLL
    expect((await screen.findAllByText('PLL')).length).toBeGreaterThanOrEqual(1)
    // mock 里 case_count=21, 页面渲染 "21 cases"
    expect(await screen.findByText(/21 cases/)).toBeInTheDocument()
  })
})

describe('useWebSocketEvents', () => {
  it('opens WS connection with correct URL and triggers handler on event', async () => {
    const handlers: Record<string, any> = {
      move_recorded: vi.fn(),
      solve_finished: vi.fn(),
    }
    // mock WebSocket
    class FakeWS {
      static instances: FakeWS[] = []
      url: string
      onopen: any = null
      onmessage: any = null
      onclose: any = null
      onerror: any = null
      sent: string[] = []
      constructor(url: string) {
        this.url = url
        FakeWS.instances.push(this)
        setTimeout(() => this.onopen?.(), 0)
      }
      send(data: string) { this.sent.push(data) }
      close() { this.onclose?.() }
    }
    ;(globalThis as any).WebSocket = FakeWS

    const TestComp = () => {
      useWebSocketEvents({ userId: 42 }, handlers)
      return null
    }
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <TestComp />
      </QueryClientProvider>
    )

    await waitFor(() => expect(FakeWS.instances.length).toBe(1))
    const ws = FakeWS.instances[0]
    expect(ws.url).toMatch(/\/ws\/user\/42$/)
    expect(ws.sent).toEqual(['ping'])  // 自动 ping

    // 模拟服务端推一个 move_recorded 事件
    ws.onmessage?.({ data: JSON.stringify({ event: 'move_recorded', ts: 0, data: {} }) })
    await waitFor(() => expect(handlers.move_recorded).toHaveBeenCalled())
  })
})

describe('Charts', () => {
  it('StageStackedBar renders rows + legend', () => {
    const rows = [
      { solve_id: 1, seq: 1, cross_ms: 1500, f2l_ms: 6000, oll_ms: 1500, pll_ms: 2000 },
      { solve_id: 2, seq: 2, cross_ms: 1600, f2l_ms: 6300, oll_ms: 1800, pll_ms: 2300 },
    ]
    render(<StageStackedBar rows={rows} />)
    expect(screen.getAllByText('Cross').length).toBeGreaterThan(0)
    expect(screen.getAllByText('F2L').length).toBeGreaterThan(0)
    expect(screen.getAllByText('OLL').length).toBeGreaterThan(0)
    expect(screen.getAllByText('PLL').length).toBeGreaterThan(0)
    expect(screen.getByText('11.00s')).toBeInTheDocument()
    expect(screen.getByText('12.00s')).toBeInTheDocument()
  })

  it('StageStackedBar shows empty message when no data', () => {
    render(<StageStackedBar rows={[]} />)
    expect(screen.getByText(/暂无数据/)).toBeInTheDocument()
  })

  it('PauseHeatmap renders 16 cells per row', () => {
    const rows = [
      { solve_id: 1, bins_ms: [0, 100, 200, 0, 500, 800, 0, 0, 1200, 300, 0, 0, 0, 0, 0, 0] },
    ]
    const { container } = render(<PauseHeatmap rows={rows} />)
    // 16 cells = 16 divs with title
    const cells = container.querySelectorAll('div[title^="solve #1"]')
    expect(cells.length).toBe(16)
  })

  it('TrendLine shows insufficient data when only 1 point', () => {
    const data = [{ session_id: 1, closed_at: Date.now(), avg3_ms: 12000, avg5_ms: 12500 }]
    render(<TrendLine data={data} />)
    expect(screen.getByText(/至少需要 2 个 session/)).toBeInTheDocument()
  })

  it('TrendLine renders svg with 2+ points', () => {
    const data = [
      { session_id: 1, closed_at: Date.now() - 86400000, avg3_ms: 12000, avg5_ms: 12500 },
      { session_id: 2, closed_at: Date.now(), avg3_ms: 11500, avg5_ms: 12000 },
    ]
    const { container } = render(<TrendLine data={data} />)
    expect(container.querySelector('svg')).toBeInTheDocument()
    // 至少 1 个 circle (avg3 marker)
    expect(container.querySelectorAll('circle').length).toBeGreaterThanOrEqual(1)
  })
})

describe('AgentPage', () => {
  it('sends a user message and shows AGENT response', async () => {
    useAppStore.setState({
      user: { id: 1, username: 'alice', timezone: 'Asia/Shanghai', created_at: 0 },
    })
    // 显式重置 mock, 并替换实现
    const mockChatStream = vi.fn().mockImplementation((_uid: any, _sid: any, _msg: any, onEvent: any) => {
      setTimeout(() => {
        onEvent('answer', { text: '你最近 PLL 慢' })
        onEvent('final', { answer: '你最近 PLL 慢', steps: 0, transcript: [] })
      }, 0)
      return () => {}
    })
    const { ai } = await import('@/api/agent')
    ;(ai as any).chatStream = mockChatStream

    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
        <MemoryRouter><AgentPage /></MemoryRouter>
      </QueryClientProvider>
    )
    // 默认初始 AGENT greeting
    expect(await screen.findByText(/你好! 我是你的魔方训练 AGENT/)).toBeInTheDocument()

    const input = screen.getByPlaceholderText(/问点什么/)
    await userEvent.type(input, '我最近瓶颈在哪{Enter}')

    await waitFor(() => expect(mockChatStream).toHaveBeenCalled())
    expect(mockChatStream.mock.calls[0].slice(0, 3)).toEqual([1, null, '我最近瓶颈在哪'])
    // 流式回调可能多次更新 placeholder 文本, 用 findAllByText 至少 1 个
    expect((await screen.findAllByText(/你最近 PLL 慢/)).length).toBeGreaterThanOrEqual(1)
  })
})
