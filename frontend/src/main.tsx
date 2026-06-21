import React from 'react'
import ReactDOM from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter } from 'react-router-dom'
import { Layout } from './components/Layout'
import { CommandCentre } from './pages/CommandCentre'
import { FundDrilldown } from './pages/FundDrilldown'
import { BLEDrilldown } from './pages/BLEDrilldown'
import { SuggestedReviews } from './pages/SuggestedReviews'
import { Copilot } from './pages/Copilot'
import { AdminRuleset } from './pages/AdminRuleset'
import { EvalDashboard } from './pages/EvalDashboard'
import { AnalystReport } from './pages/AnalystReport'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 30_000 } },
})

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: '/', element: <CommandCentre /> },
      { path: '/funds/:fundId', element: <FundDrilldown /> },
      { path: '/bles/:bleId', element: <BLEDrilldown /> },
      { path: '/reviews', element: <SuggestedReviews /> },
      { path: '/copilot', element: <Copilot /> },
      { path: '/admin/ruleset', element: <AdminRuleset /> },
      { path: '/evals', element: <EvalDashboard /> },
      { path: '/reports/:scope/:scopeId', element: <AnalystReport /> },
    ],
  },
])

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>,
)
