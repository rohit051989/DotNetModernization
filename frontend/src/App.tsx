import { useEffect, useState } from 'react'
import { listEngagements } from './api/catalog'
import { getExecution } from './api/workflow'
import { getRepository } from './api/repositories'
import type { Engagement } from './types/catalog'
import { AppShell } from './components/AppShell'
import type { TabKey } from './components/TabBar'
import { CatalogPage } from './pages/CatalogPage'
import { RepositoriesPage } from './pages/RepositoriesPage'
import { DashboardPage } from './pages/DashboardPage'
import { EstatePage } from './pages/EstatePage'
import { WorkflowPage } from './pages/WorkflowPage'
import { WorkflowAdministrationPage } from './pages/admin/WorkflowAdministrationPage'
import { UsersPage } from './pages/admin/UsersPage'
import { SignInPage } from './pages/SignInPage'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { ToastProvider } from './components/Toast'
import {
  parseExecutionIdFromLocation,
  parseRepositoryIdFromLocation,
  pushExecutionRoute,
  pushRepositoryRoute,
  pushRootRoute,
} from './routing'

/** Every call needs a signed-in session (app.auth): until there is one, the sign-in page. */
function App() {
  return (
    <AuthProvider>
      <SignedIn />
    </AuthProvider>
  )
}

function SignedIn() {
  const { me, setMe } = useAuth()
  if (me === undefined) return <p className="p-6 text-sm text-neutral-400">Checking sign-in…</p>
  if (me === null) return <SignInPage onSignedIn={setMe} />
  return <PlatformApp />
}

// A reload keeps the engagement and tab the person was in: kept for this browser tab only.
const VIEW_KEY = 'platform:view'

function rememberedView(): { engagementId: string | null; tab: TabKey } {
  try {
    const saved = JSON.parse(window.sessionStorage.getItem(VIEW_KEY) ?? 'null')
    if (saved && typeof saved === 'object') {
      return { engagementId: typeof saved.engagementId === 'string' ? saved.engagementId : null, tab: saved.tab ?? 'catalog' }
    }
  } catch {
    // no storage, or not ours: start from the master catalog
  }
  return { engagementId: null, tab: 'catalog' }
}

function PlatformApp() {
  const [selectedEngagementId, setSelectedEngagementId] = useState<string | null>(() => rememberedView().engagementId)
  const [engagements, setEngagements] = useState<Engagement[]>([])
  const [activeTab, setActiveTab] = useState<TabKey>(() => rememberedView().tab)

  useEffect(() => {
    try {
      window.sessionStorage.setItem(VIEW_KEY, JSON.stringify({ engagementId: selectedEngagementId, tab: activeTab }))
    } catch {
      // storage unavailable: a reload starts from the master catalog
    }
  }, [selectedEngagementId, activeTab])
  // A repository page's SOAP call, to open at its row in the Estate tab's SOAP report.
  const [estateSoapFocus, setEstateSoapFocus] = useState<string | null>(null)
  const [selectedExecutionId, setSelectedExecutionId] = useState<string | null>(null)
  // A repository detail is a page of its own (/repositories/<id>), owned
  // here like an execution so the URL, Back and reload all work.
  const [selectedRepositoryId, setSelectedRepositoryId] = useState<string | null>(null)

  useEffect(() => {
    listEngagements()
      .then((found) => {
        setEngagements(found)
        // A remembered engagement deleted since: back to the master catalog.
        const remembered = rememberedView().engagementId
        if (remembered && !found.some((e) => e.id === remembered) && !parseRepositoryIdFromLocation() && !parseExecutionIdFromLocation()) {
          setSelectedEngagementId(null)
          setActiveTab('catalog')
        }
      })
      .catch(() => setEngagements([]))
  }, [])

  // Resolve a deep-linked execution URL on load — 20-WORKFLOW-OBSERVABILITY-UI.md
  // Part C: "an execution can be linked to and reloaded directly." The
  // engagement isn't in the URL, so it's resolved from the execution's own
  // parameters.engagement_id.
  useEffect(() => {
    const executionId = parseExecutionIdFromLocation()
    if (!executionId) return
    getExecution(executionId)
      .then((execution) => {
        const engagementId = typeof execution.parameters.engagement_id === 'string' ? execution.parameters.engagement_id : null
        if (engagementId) setSelectedEngagementId(engagementId)
        setActiveTab('workflow')
        setSelectedExecutionId(executionId)
      })
      .catch(() => {
        // Leave the URL as-is; WorkflowPage's "not found" state below handles it
        // once an engagement is selected. Without one, fall back to Catalog.
        setActiveTab('workflow')
        setSelectedExecutionId(executionId)
      })
  }, [])

  // The same for a deep-linked repository: its engagement comes from the row.
  useEffect(() => {
    const repositoryId = parseRepositoryIdFromLocation()
    if (!repositoryId) return
    getRepository(repositoryId)
      .then((repo) => {
        setSelectedEngagementId(repo.engagement_id)
        setActiveTab('repositories')
        setSelectedRepositoryId(repositoryId)
      })
      .catch(() => pushRootRoute())
  }, [])

  useEffect(() => {
    function handlePopState() {
      const executionId = parseExecutionIdFromLocation()
      setSelectedExecutionId(executionId)
      if (executionId) setActiveTab('workflow')
      const repositoryId = parseRepositoryIdFromLocation()
      setSelectedRepositoryId(repositoryId)
      if (repositoryId) setActiveTab('repositories')
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function handleSelectEngagement(engagementId: string | null) {
    setSelectedEngagementId(engagementId)
    if (selectedRepositoryId) {
      setSelectedRepositoryId(null)
      pushRootRoute()
    }
    // Repositories/Dashboard/Workflow are engagement-only — Master Catalog has
    // nothing to show there, so fall back to the one tab that always exists.
    if (engagementId === null && activeTab !== 'catalog' && activeTab !== 'admin') {
      setActiveTab('catalog')
    }
    // The mirror image: Workflow Administration is master-only — selecting
    // an engagement leaves nothing to show there either.
    if (engagementId !== null && activeTab === 'admin') {
      setActiveTab('catalog')
    }
  }

  function handleSelectTab(tab: TabKey) {
    setActiveTab(tab)
    if (tab !== 'workflow' && selectedExecutionId) {
      setSelectedExecutionId(null)
      pushRootRoute()
    }
    // Clicking Repositories again from a repository page returns to the list.
    if (selectedRepositoryId) {
      setSelectedRepositoryId(null)
      pushRootRoute()
    }
  }

  function handleSelectRepository(repositoryId: string | null) {
    setSelectedRepositoryId(repositoryId)
    if (repositoryId) pushRepositoryRoute(repositoryId)
    else pushRootRoute()
  }

  function handleNavigateToExecution(executionId: string) {
    setActiveTab('workflow')
    setSelectedExecutionId(executionId)
    pushExecutionRoute(executionId)
  }

  function handleSelectExecution(executionId: string | null) {
    setSelectedExecutionId(executionId)
    if (executionId) pushExecutionRoute(executionId)
    else pushRootRoute()
  }

  const engagementName =
    engagements.find((engagement) => engagement.id === selectedEngagementId)?.client_name ??
    selectedEngagementId ??
    ''

  return (
    <ToastProvider>
      <AppShell
        engagements={engagements}
        selectedEngagementId={selectedEngagementId}
        onSelectEngagement={handleSelectEngagement}
        onEngagementCreated={(engagement) => {
          setEngagements((current) => [...current, engagement].sort((a, b) => a.id.localeCompare(b.id)))
          handleSelectEngagement(engagement.id)
        }}
        activeTab={activeTab}
        onSelectTab={handleSelectTab}
      >
        {selectedExecutionId ? (
          // A deep-linked execution renders regardless of engagement/tab
          // state — 20-WORKFLOW-OBSERVABILITY-UI.md Part E: "Execution not
          // found — clear message ..., not a blank screen" must work even
          // when the execution (and so its engagement) never resolved.
          <WorkflowPage
            engagementId={selectedEngagementId ?? ''}
            selectedExecutionId={selectedExecutionId}
            onSelectExecution={handleSelectExecution}
            onNavigateToRepositories={() => setActiveTab('repositories')}
          />
        ) : activeTab === 'repositories' && selectedEngagementId ? (
          <RepositoriesPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            engagementName={engagementName}
            selectedRepositoryId={selectedRepositoryId}
            onSelectRepository={handleSelectRepository}
            onNavigateToExecution={handleNavigateToExecution}
            onEngagementDeleted={(deletedId) => {
              setEngagements((current) => current.filter((e) => e.id !== deletedId))
              handleSelectEngagement(null)
            }}
            onOpenEstateSoap={(invocationId) => {
              setEstateSoapFocus(invocationId)
              handleSelectRepository(null)
              setActiveTab('estate')
            }}
          />
        ) : activeTab === 'dashboard' && selectedEngagementId ? (
          <DashboardPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            onNavigateToRepositories={() => setActiveTab('repositories')}
            onNavigateToExecution={handleNavigateToExecution}
          />
        ) : activeTab === 'estate' && selectedEngagementId ? (
          <EstatePage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            focusSoapInvocation={estateSoapFocus}
            onFocusShown={() => setEstateSoapFocus(null)}
            onOpenRepository={(repositoryId) => {
              setActiveTab('repositories')
              handleSelectRepository(repositoryId)
            }}
          />
        ) : activeTab === 'workflow' && selectedEngagementId ? (
          <WorkflowPage
            key={selectedEngagementId}
            engagementId={selectedEngagementId}
            selectedExecutionId={selectedExecutionId}
            onSelectExecution={handleSelectExecution}
            onNavigateToRepositories={() => setActiveTab('repositories')}
          />
        ) : activeTab === 'admin' && !selectedEngagementId ? (
          <WorkflowAdministrationPage />
        ) : activeTab === 'users' ? (
          <UsersPage />
        ) : (
          <CatalogPage engagements={engagements} selectedEngagementId={selectedEngagementId} />
        )}
      </AppShell>
    </ToastProvider>
  )
}

export default App
