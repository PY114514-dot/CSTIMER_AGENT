import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useAppStore } from '@/store/app'
import AppShell from '@/components/AppShell'
import LoginPage from '@/pages/LoginPage'
import DashboardPage from '@/pages/DashboardPage'
import TimerPage from '@/pages/TimerPage'
import TrainingListPage from '@/pages/TrainingListPage'
import TrainingDrillPage from '@/pages/TrainingDrillPage'
import FormulasPage from '@/pages/FormulasPage'
import AgentPage from '@/pages/AgentPage'
import ReplayPage from '@/pages/ReplayPage'
import DevicesPage from '@/pages/DevicesPage'
import './styles.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false } },
})

function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useAppStore(s => s.user)
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RequireAuth><AppShell /></RequireAuth>}>
            <Route path="/" element={<DashboardPage />} />
            <Route path="/timer" element={<TimerPage />} />
            <Route path="/training" element={<TrainingListPage />} />
            <Route path="/training/:taskId" element={<TrainingDrillPage />} />
            <Route path="/formulas" element={<FormulasPage />} />
            <Route path="/agent" element={<AgentPage />} />
            <Route path="/replay" element={<ReplayPage />} />
            <Route path="/devices" element={<DevicesPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
)
