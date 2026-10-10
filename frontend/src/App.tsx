import { AuthProvider, useAuth } from '@/lib/auth'
import { TenantProvider, useTenants } from '@/lib/tenants'
import { usePermissions } from '@/lib/permissions'
import { parseRoute, useRoute } from '@/lib/router'
import { ToastProvider } from '@/components/ui/toast'
import { LoginView } from '@/components/auth/login-view'
import { AppShell } from '@/components/layout/app-shell'
import { PageHeader } from '@/components/layout/page-header'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { Button } from '@/components/ui/button'
import { TenantList } from '@/components/tenants/tenant-list'
import { TenantOverview } from '@/components/tenants/tenant-overview'
import { ProfileEditor } from '@/components/tenants/profile-editor'
import { MenuPreview } from '@/components/tenants/menu-preview'
import { MenuEditor } from '@/components/tenants/menu-editor'
import { OfferingsPanel } from '@/components/tenants/offerings-panel'
import { RecordsPanel } from '@/components/tenants/records-panel'
import { CustomersPanel } from '@/components/tenants/customers-panel'
import { OrdersPanel } from '@/components/tenants/orders-panel'
import { CampaignsPanel } from '@/components/tenants/campaigns-panel'
import { DistributorsPanel } from '@/components/tenants/distributors-panel'
import { ChatHistoryPanel } from '@/components/tenants/chat-history-panel'
import { LiveInboxPanel } from '@/components/tenants/live-inbox-panel'
import { ComplaintsPanel } from '@/components/tenants/complaints-panel'
import { UploadsPanel } from '@/components/tenants/uploads-panel'
import { AdminChatPanel } from '@/components/tenants/admin-chat'
import { IntentsAndFlows } from '@/components/tenants/intents-and-flows'
import { InfoPagePanel } from '@/components/tenants/info-page-panel'
import { VersionsPanel } from '@/components/tenants/versions-panel'
import { LayersPanel } from '@/components/tenants/layers-panel'
import { TokensPanel } from '@/components/tenants/tokens-panel'
import { TestAndSmoke } from '@/components/tenants/test-and-smoke'
import { TeamScreen } from '@/components/team/team-screen'
import { RegisterWizard } from '@/components/onboarding/register-wizard'
import { ApiOnboardingPanel } from '@/components/tenants/api-onboarding-panel'
import { ApiOnboardingReview } from '@/components/team/api-onboarding-review'
import { AuditHistory } from '@/components/team/audit-history'
import { TenantChangeReview, MyTenantChangeRequests } from '@/components/tenants/tenant-approvals-panel'
import { CallbacksPanel } from '@/components/tenants/callbacks-panel'
import { CallbackDetailPanel } from '@/components/tenants/callback-detail-panel'

function Router() {
  const route = parseRoute(useRoute())
  const { canManageTenants, canManageTeam, isSuperAdmin, can } = usePermissions()
  const { identity } = useAuth()

  if (route.view === 'register') {
    // Admins can view and edit the registration panel; their submission goes
    // to the super admin approval queue instead of publishing directly.
    if (!canManageTenants && identity?.role !== 'admin') return <NotPermitted what="register tenants" />
    return (
      <AppShell route={route}>
        <RegisterWizard />
      </AppShell>
    )
  }

  if (route.view === 'tenant-requests') {
    if (isSuperAdmin) {
      return (
        <AppShell route={route}>
          <TenantChangeReview />
        </AppShell>
      )
    }
    if (identity && (identity.role === 'admin' || identity.role === 'sub_admin') && canManageTenants) {
      return (
        <AppShell route={route}>
          <MyTenantChangeRequests />
        </AppShell>
      )
    }
    return <NotPermitted what="view tenant change requests" />
  }

  if (route.view === 'team') {
    if (!canManageTeam) return <NotPermitted what="manage the team" />
    return (
      <AppShell route={route}>
        <TeamScreen />
      </AppShell>
    )
  }

  if (route.view === 'api-requests') {
    if (!isSuperAdmin) return <NotPermitted what="review API access requests" />
    return (
      <AppShell route={route}>
        <ApiOnboardingReview />
      </AppShell>
    )
  }

  if (route.view === 'audit-history') {
    if (!isSuperAdmin) return <NotPermitted what="view audit history" />
    return (
      <AppShell route={route}>
        <AuditHistory />
      </AppShell>
    )
  }

  if (!route.tenantId) {
    return (
      <AppShell route={route}>
        <TenantList />
      </AppShell>
    )
  }

  const writeViews = new Set(['profile', 'menu-edit', 'versions', 'tokens'])
  if (route.view === 'api-access') {
    if (isSuperAdmin || !identity?.tenant_id || route.tenantId !== identity.tenant_id || !can('manage_operations')) {
      return <AppShell route={route}><NotPermitted what="request API access for this tenant" /></AppShell>
    }
    return (
      <AppShell route={route}>
        <ApiOnboardingPanel />
      </AppShell>
    )
  }

  if (writeViews.has(route.view) && !canManageTenants) {
    return (
      <AppShell route={route}>
        <NotPermitted what="change tenant configuration" />
      </AppShell>
    )
  }

  return (
    <AppShell route={route}>
      {route.view === 'overview' && <TenantOverview tenantId={route.tenantId} />}
      {route.view === 'profile' && <ProfileEditor tenantId={route.tenantId} />}
      {route.view === 'menu' && <MenuPreview tenantId={route.tenantId} />}
      {route.view === 'menu-edit' && (
        <MenuEditor tenantId={route.tenantId} focusId={route.query.get('focus')} />
      )}
      {route.view === 'flows' && <IntentsAndFlows tenantId={route.tenantId} />}
      {route.view === 'records' && <RecordsPanel tenantId={route.tenantId} />}
      {route.view === 'customers' && <CustomersPanel tenantId={route.tenantId} />}
      {route.view === 'orders' && <OrdersPanel tenantId={route.tenantId} />}
      {route.view === 'campaigns' && <CampaignsPanel tenantId={route.tenantId} />}
      {route.view === 'distributors' && <DistributorsPanel tenantId={route.tenantId} />}
      {route.view === 'offerings' && <OfferingsPanel tenantId={route.tenantId} />}
      {route.view === 'projects' && <InfoPagePanel tenantId={route.tenantId} page="projects" />}
      {route.view === 'technologies' && <InfoPagePanel tenantId={route.tenantId} page="technologies" />}
      {route.view === 'careers' && <InfoPagePanel tenantId={route.tenantId} page="careers" />}
      {route.view === 'benefits' && <InfoPagePanel tenantId={route.tenantId} page="benefits" />}
      {route.view === 'chat-history' && <ChatHistoryPanel tenantId={route.tenantId} />}
      {route.view === 'inbox' && <LiveInboxPanel tenantId={route.tenantId} />}
      {route.view === 'complaints' && <ComplaintsPanel tenantId={route.tenantId} />}
      {route.view === 'uploads' && <UploadsPanel tenantId={route.tenantId} />}
      {route.view === 'chat' && <AdminChatPanel tenantId={route.tenantId} />}
      {route.view === 'versions' && <VersionsPanel tenantId={route.tenantId} />}
      {route.view === 'layers' && <LayersPanel tenantId={route.tenantId} />}
      {route.view === 'tokens' && <TokensPanel tenantId={route.tenantId} />}
      {route.view === 'test' && <TestAndSmoke tenantId={route.tenantId} />}
      {route.view === 'callbacks' && <CallbacksPanel />}
      {route.view === 'callback' && <CallbackDetailPanel />}
      {PENDING_VIEWS.has(route.view) && <ComingSoon view={route.view} />}
      {!KNOWN_VIEWS.includes(route.view) && (
        <Alert tone="warning" title="Unknown view">
          <code>{route.view}</code> is not a screen in this console.
        </Alert>
      )}
    </AppShell>
  )
}

/**
 * Views the sidebar advertises before their screens are built. Keeping them
 * listed (rather than hidden) is deliberate: the navigation is the contract,
 * and a dead link with an honest label beats a silently missing capability.
 * Every info page now has its panel — this stays empty until the next one.
 */
const PENDING_VIEWS = new Set<string>([])

const KNOWN_VIEWS = [
  'overview',
  'profile',
  'menu',
  'menu-edit',
  'flows',
  'records',
  'offerings',
  'customers',
  'orders',
  'campaigns',
  'distributors',
  'projects',
  'technologies',
  'careers',
  'benefits',
  'uploads',
  'chat',
  'chat-history',
  'inbox',
  'complaints',
  'versions',
  'layers',
  'tokens',
  'test',
  'callbacks',
  'callback',
  'api-access',
  'tenant-requests',
  'api-requests',
  'audit-history',
]

function ComingSoon({ view }: { view: string }) {
  const label = view.replace(/-/g, ' ')
  return (
    <div>
      <PageHeader title={label.replace(/\b\w/g, (c) => c.toUpperCase())} />
      <Alert tone="info" title="Coming next">
        This screen is wired into the navigation but its panel is not built yet.
      </Alert>
    </div>
  )
}

function NotPermitted({ what }: { what: string }) {
  return (
    <div className="mx-auto max-w-lg py-16">
      <Alert tone="warning" title="Not permitted">
        Your account cannot {what}. This screen needs the{' '}
        <strong>manage_operations</strong> permission — a super admin can grant it under Team &amp; permissions.
      </Alert>
    </div>
  )
}

function AuthedApp() {
  const { loading, identity } = useAuth()
  const { tenants, loading: tenantsLoading, error, reload } = useTenants()
  const route = parseRoute(useRoute())
  const { canManageTeam } = usePermissions()

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingBlock label="Connecting to the backend…" />
      </div>
    )
  }

  if (!identity) return <LoginView />

  // The tenant registry needs manage_operations. Without it, skip it and let
  // the admin work inside the team screen (or sign in as someone who can).
  if (error && canManageTeam && route.view !== 'team') {
    return (
      <div className="mx-auto max-w-lg px-6 py-20">
        <Alert tone="danger" title="Cannot list tenants">
          {error}
        </Alert>
        <Button className="mt-4" onClick={reload}>
          Retry
        </Button>
      </div>
    )
  }

  if (tenantsLoading && !tenants.length && route.view !== 'register' && error) {
    return (
      <div className="flex h-full items-center justify-center">
        <LoadingBlock label="Loading tenants…" />
      </div>
    )
  }

  return <Router />
}

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <TenantProvider>
          <div className="h-full">
            <AuthedApp />
          </div>
        </TenantProvider>
      </AuthProvider>
    </ToastProvider>
  )
}