import Dashboard from './pages/Dashboard'
import PortalPage from './components/portal/PortalPage'

export default function App() {
  const path = window.location.pathname
  const match = path.match(/^\/resolve\/(.+)$/)
  if (match) {
    return <PortalPage token={decodeURIComponent(match[1])} />
  }
  return <Dashboard />
}
