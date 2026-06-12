import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAppStore } from '@/store/app'
import AppShell from '@/components/AppShell'
import DashboardPage from '@/pages/DashboardPage'
import TimerPage from '@/pages/TimerPage'
import TrainingListPage from '@/pages/TrainingListPage'
import TrainingDrillPage from '@/pages/TrainingDrillPage'
import FormulasPage from '@/pages/FormulasPage'
import AgentPage from '@/pages/AgentPage'
import ReplayPage from '@/pages/ReplayPage'
import DevicesPage from '@/pages/DevicesPage'
import './styles.css'
// 触发 GAN / MoYu / QiYi 适配器自注册
import './services/smart-cube'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

// 【已移除登录页】直接用本地默认 user 启动, 避免登录 500 错误
// 如果后端默认用户的 id 不是 1, 改下面这一行的 id 即可
useAppStore.getState()._bootDefaultUser?.()

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppShell />}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/timer" element={<TimerPage />} />
            <Route path="/training" element={<TrainingListPage />} />
            <Route path="/training/:taskId" element={<TrainingDrillPage />} />
            <Route path="/formulas" element={<FormulasPage />} />
            <Route path="/agent" element={<AgentPage />} />
            <Route path="/replay" element={<ReplayPage />} />
            <Route path="/devices" element={<DevicesPage />} />
            <Route path="*" element={<DashboardPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
