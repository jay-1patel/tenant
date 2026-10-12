import { useEffect, useState, useCallback } from 'react'
import { Card, CardHeader, CardBody } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { Badge } from '@/components/ui/badge'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { request } from '@/lib/api'
import { GoogleConnectPanel } from '@/components/tenants/google-connect-panel'
import {
  CreditCard,
  Truck,
  Video,
  Zap,
} from 'lucide-react'

interface IntegrationData {
  provider: string
  api_type: 'payment_api' | 'order_api'
  environment: 'sandbox' | 'production'
  is_active: boolean
  status: string
  credentials: Record<string, string>
  webhook_secret?: string
  last_error?: string
  updated_at?: string
}

interface IntegrationsResponse {
  ok: boolean
  integrations: IntegrationData[]
}

export function IntegrationsPanel({ tenantId }: { tenantId: string }) {
  const { push: showToast } = useToast()
  const [activeTab, setActiveTab] = useState<'payments' | 'shipping' | 'meetings'>('payments')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState<string | null>(null)
  const [testing, setTesting] = useState<string | null>(null)
  const [testResults, setTestResults] = useState<Record<string, { ok: boolean; message: string }>>({})

  // Form states
  const [razorpay, setRazorpay] = useState({
    environment: 'sandbox' as 'sandbox' | 'production',
    is_active: true,
    key_id: '',
    key_secret: '',
    webhook_secret: '',
    status: 'not_configured',
  })

  const [stripe, setStripe] = useState({
    environment: 'sandbox' as 'sandbox' | 'production',
    is_active: false,
    publishable_key: '',
    secret_key: '',
    webhook_secret: '',
    status: 'not_configured',
  })

  const [bluedart, setBluedart] = useState({
    environment: 'sandbox' as 'sandbox' | 'production',
    is_active: false,
    customer_code: '',
    license_key: '',
    login_id: 'BD_USER',
    status: 'not_configured',
  })

  const [xpressbees, setXpressbees] = useState({
    environment: 'sandbox' as 'sandbox' | 'production',
    is_active: false,
    email: '',
    password: '',
    token: '',
    status: 'not_configured',
  })

  const loadIntegrations = useCallback(async () => {
    if (!tenantId) return
    try {
      setLoading(true)
      const res = await request<IntegrationsResponse>(`/api/tenants/${tenantId}/integrations`)
      if (res && res.integrations) {
        res.integrations.forEach((item) => {
          const prov = item.provider.toLowerCase()
          const creds = item.credentials || {}
          if (prov === 'razorpay') {
            setRazorpay({
              environment: item.environment || 'sandbox',
              is_active: Boolean(item.is_active),
              key_id: creds.key_id || creds.api_key || '',
              key_secret: creds.key_secret || creds.secret || '',
              webhook_secret: item.webhook_secret || '',
              status: item.status || 'configured',
            })
          } else if (prov === 'stripe') {
            setStripe({
              environment: item.environment || 'sandbox',
              is_active: Boolean(item.is_active),
              publishable_key: creds.publishable_key || creds.api_key || '',
              secret_key: creds.secret_key || creds.secret || '',
              webhook_secret: item.webhook_secret || '',
              status: item.status || 'configured',
            })
          } else if (prov === 'bluedart' || prov === 'blue_dart') {
            setBluedart({
              environment: item.environment || 'sandbox',
              is_active: Boolean(item.is_active),
              customer_code: creds.customer_code || '',
              license_key: creds.license_key || '',
              login_id: creds.login_id || 'BD_USER',
              status: item.status || 'configured',
            })
          } else if (prov === 'xpressbees') {
            setXpressbees({
              environment: item.environment || 'sandbox',
              is_active: Boolean(item.is_active),
              email: creds.email || '',
              password: creds.password || '',
              token: creds.token || creds.api_token || '',
              status: item.status || 'configured',
            })
          }
        })
      }
    } catch (err) {
      console.error('Failed to load integrations:', err)
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    loadIntegrations()
  }, [loadIntegrations])

  const handleSave = async (provider: string) => {
    try {
      setSaving(provider)
      let payload: Record<string, any> = {}

      if (provider === 'razorpay') {
        payload = {
          api_type: 'payment_api',
          environment: razorpay.environment,
          is_active: razorpay.is_active,
          credentials: { key_id: razorpay.key_id, key_secret: razorpay.key_secret },
          webhook_secret: razorpay.webhook_secret,
        }
      } else if (provider === 'stripe') {
        payload = {
          api_type: 'payment_api',
          environment: stripe.environment,
          is_active: stripe.is_active,
          credentials: { publishable_key: stripe.publishable_key, secret_key: stripe.secret_key },
          webhook_secret: stripe.webhook_secret,
        }
      } else if (provider === 'bluedart') {
        payload = {
          api_type: 'order_api',
          environment: bluedart.environment,
          is_active: bluedart.is_active,
          credentials: {
            customer_code: bluedart.customer_code,
            license_key: bluedart.license_key,
            login_id: bluedart.login_id,
          },
        }
      } else if (provider === 'xpressbees') {
        payload = {
          api_type: 'order_api',
          environment: xpressbees.environment,
          is_active: xpressbees.is_active,
          credentials: {
            email: xpressbees.email,
            password: xpressbees.password,
            token: xpressbees.token,
          },
        }
      }

      await request(`/api/tenants/${tenantId}/integrations/${provider}`, {
        method: 'POST',
        body: payload,
      })
      showToast(`${provider.toUpperCase()} configuration saved successfully!`, 'success')
      loadIntegrations()
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Save failed', 'error')
    } finally {
      setSaving(null)
    }
  }

  const handleTest = async (provider: string) => {
    try {
      setTesting(provider)
      let creds: Record<string, any> = {}
      let env = 'sandbox'

      if (provider === 'razorpay') {
        creds = { key_id: razorpay.key_id, key_secret: razorpay.key_secret }
        env = razorpay.environment
      } else if (provider === 'stripe') {
        creds = { secret_key: stripe.secret_key }
        env = stripe.environment
      } else if (provider === 'bluedart') {
        creds = {
          customer_code: bluedart.customer_code,
          license_key: bluedart.license_key,
          login_id: bluedart.login_id,
        }
        env = bluedart.environment
      } else if (provider === 'xpressbees') {
        creds = {
          email: xpressbees.email,
          password: xpressbees.password,
          token: xpressbees.token,
        }
        env = xpressbees.environment
      }

      const res = await request<{ ok: boolean; message?: string; error?: string }>(
        `/api/tenants/${tenantId}/integrations/${provider}/test`,
        {
          method: 'POST',
          body: {
            api_type: provider.includes('dart') || provider.includes('xpress') ? 'order_api' : 'payment_api',
            environment: env,
            credentials: creds,
          },
        },
      )

      if (res.ok) {
        setTestResults((prev) => ({
          ...prev,
          [provider]: { ok: true, message: res.message || 'Connection verified successfully!' },
        }))
        showToast(`${provider.toUpperCase()} connection verified!`, 'success')
      } else {
        setTestResults((prev) => ({
          ...prev,
          [provider]: { ok: false, message: res.error || 'Connection failed' },
        }))
        showToast(`${provider.toUpperCase()} test failed: ${res.error || 'Connection rejected'}`, 'error')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Test failed'
      setTestResults((prev) => ({ ...prev, [provider]: { ok: false, message: msg } }))
      showToast(`Test error: ${msg}`, 'error')
    } finally {
      setTesting(null)
    }
  }

  const renderBadge = (status: string, isActive: boolean) => {
    if (!isActive) {
      return <Badge tone="muted">Disabled</Badge>
    }
    if (status === 'verified') {
      return <Badge tone="success">Verified Active</Badge>
    }
    if (status === 'configured') {
      return <Badge tone="accent">Configured</Badge>
    }
    return <Badge tone="neutral">Not Configured</Badge>
  }

  if (loading) {
    return <LoadingBlock label="Loading integrations…" />
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Payment & Logistics Integrations"
        description="Configure connected APIs for payment gateways (Razorpay, Stripe), courier logistics (Blue Dart, Xpressbees), and Google Meet."
      />

      {/* Tabs */}
      <div className="flex border-b border-surface-line gap-4 text-sm font-medium">
        <button
          type="button"
          onClick={() => setActiveTab('payments')}
          className={`flex items-center gap-2 pb-3 border-b-2 transition-colors ${
            activeTab === 'payments'
              ? 'border-accent-500 text-accent-400 font-semibold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <CreditCard className="h-4 w-4" />
          Payment Gateways
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('shipping')}
          className={`flex items-center gap-2 pb-3 border-b-2 transition-colors ${
            activeTab === 'shipping'
              ? 'border-accent-500 text-accent-400 font-semibold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Truck className="h-4 w-4" />
          Logistics & Courier
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('meetings')}
          className={`flex items-center gap-2 pb-3 border-b-2 transition-colors ${
            activeTab === 'meetings'
              ? 'border-accent-500 text-accent-400 font-semibold'
              : 'border-transparent text-slate-400 hover:text-slate-200'
          }`}
        >
          <Video className="h-4 w-4" />
          Google Calendar & Meet
        </button>
      </div>

      {/* PAYMENTS TAB */}
      {activeTab === 'payments' && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Razorpay */}
          <Card>
            <CardHeader
              title="Razorpay Gateway"
              description="UPI, Net Banking, Cards & Wallets for WhatsApp checkout"
              icon={<CreditCard className="h-5 w-5 text-accent-400" />}
              actions={renderBadge(razorpay.status, razorpay.is_active)}
            />
            <CardBody className="space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-surface-line/60">
                <span className="text-xs text-slate-300 font-medium">Enable Razorpay</span>
                <Switch
                  checked={razorpay.is_active}
                  onChange={(val: boolean) => setRazorpay((p) => ({ ...p, is_active: val }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Environment</label>
                <select
                  value={razorpay.environment}
                  onChange={(e) =>
                    setRazorpay((p) => ({ ...p, environment: e.target.value as 'sandbox' | 'production' }))
                  }
                  className="w-full rounded-lg bg-surface-overlay border border-surface-line px-3 py-2 text-xs text-slate-200"
                >
                  <option value="sandbox">Sandbox (Test Mode)</option>
                  <option value="production">Production (Live Mode)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Razorpay Key ID</label>
                <Input
                  value={razorpay.key_id}
                  placeholder="rzp_test_..."
                  onChange={(e) => setRazorpay((p) => ({ ...p, key_id: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Razorpay Key Secret</label>
                <Input
                  type="password"
                  value={razorpay.key_secret}
                  placeholder="••••••••••••••••"
                  onChange={(e) => setRazorpay((p) => ({ ...p, key_secret: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Webhook Secret (Optional)</label>
                <Input
                  type="password"
                  value={razorpay.webhook_secret}
                  placeholder="whsec_..."
                  onChange={(e) => setRazorpay((p) => ({ ...p, webhook_secret: e.target.value }))}
                />
                <p className="mt-1 text-[11px] text-slate-500 font-mono">
                  Webhook URL: {window.location.origin}/api/webhooks/payments/{tenantId}/razorpay
                </p>
              </div>

              {testResults['razorpay'] && (
                <Alert
                  tone={testResults['razorpay'].ok ? 'success' : 'danger'}
                  title={testResults['razorpay'].ok ? 'Test Passed' : 'Test Failed'}
                >
                  {testResults['razorpay'].message}
                </Alert>
              )}

              <div className="flex gap-2 pt-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => handleSave('razorpay')}
                  loading={saving === 'razorpay'}
                >
                  Save Razorpay
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTest('razorpay')}
                  loading={testing === 'razorpay'}
                  icon={<Zap className="h-3.5 w-3.5" />}
                >
                  Test Connection
                </Button>
              </div>
            </CardBody>
          </Card>

          {/* Stripe */}
          <Card>
            <CardHeader
              title="Stripe Gateway"
              description="Global multi-currency credit/debit card checkout"
              icon={<CreditCard className="h-5 w-5 text-accent-400" />}
              actions={renderBadge(stripe.status, stripe.is_active)}
            />
            <CardBody className="space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-surface-line/60">
                <span className="text-xs text-slate-300 font-medium">Enable Stripe</span>
                <Switch
                  checked={stripe.is_active}
                  onChange={(val: boolean) => setStripe((p) => ({ ...p, is_active: val }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Environment</label>
                <select
                  value={stripe.environment}
                  onChange={(e) =>
                    setStripe((p) => ({ ...p, environment: e.target.value as 'sandbox' | 'production' }))
                  }
                  className="w-full rounded-lg bg-surface-overlay border border-surface-line px-3 py-2 text-xs text-slate-200"
                >
                  <option value="sandbox">Sandbox (Test Mode)</option>
                  <option value="production">Production (Live Mode)</option>
                </select>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Publishable Key</label>
                <Input
                  value={stripe.publishable_key}
                  placeholder="pk_test_..."
                  onChange={(e) => setStripe((p) => ({ ...p, publishable_key: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Secret Key</label>
                <Input
                  type="password"
                  value={stripe.secret_key}
                  placeholder="sk_test_..."
                  onChange={(e) => setStripe((p) => ({ ...p, secret_key: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Webhook Secret (whsec_...)</label>
                <Input
                  type="password"
                  value={stripe.webhook_secret}
                  placeholder="whsec_..."
                  onChange={(e) => setStripe((p) => ({ ...p, webhook_secret: e.target.value }))}
                />
                <p className="mt-1 text-[11px] text-slate-500 font-mono">
                  Webhook URL: {window.location.origin}/api/webhooks/payments/{tenantId}/stripe
                </p>
              </div>

              {testResults['stripe'] && (
                <Alert
                  tone={testResults['stripe'].ok ? 'success' : 'danger'}
                  title={testResults['stripe'].ok ? 'Test Passed' : 'Test Failed'}
                >
                  {testResults['stripe'].message}
                </Alert>
              )}

              <div className="flex gap-2 pt-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => handleSave('stripe')}
                  loading={saving === 'stripe'}
                >
                  Save Stripe
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTest('stripe')}
                  loading={testing === 'stripe'}
                  icon={<Zap className="h-3.5 w-3.5" />}
                >
                  Test Connection
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* SHIPPING TAB */}
      {activeTab === 'shipping' && (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Blue Dart */}
          <Card>
            <CardHeader
              title="Blue Dart Express"
              description="Automated AWB generation and live tracking API"
              icon={<Truck className="h-5 w-5 text-accent-400" />}
              actions={renderBadge(bluedart.status, bluedart.is_active)}
            />
            <CardBody className="space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-surface-line/60">
                <span className="text-xs text-slate-300 font-medium">Enable Blue Dart</span>
                <Switch
                  checked={bluedart.is_active}
                  onChange={(val: boolean) => setBluedart((p) => ({ ...p, is_active: val }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Customer Account Code</label>
                <Input
                  value={bluedart.customer_code}
                  placeholder="BD_CUST_1001"
                  onChange={(e) => setBluedart((p) => ({ ...p, customer_code: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">License Key</label>
                <Input
                  type="password"
                  value={bluedart.license_key}
                  placeholder="••••••••••••••••"
                  onChange={(e) => setBluedart((p) => ({ ...p, license_key: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Login ID / User</label>
                <Input
                  value={bluedart.login_id}
                  placeholder="BD_USER"
                  onChange={(e) => setBluedart((p) => ({ ...p, login_id: e.target.value }))}
                />
              </div>

              {testResults['bluedart'] && (
                <Alert
                  tone={testResults['bluedart'].ok ? 'success' : 'danger'}
                  title={testResults['bluedart'].ok ? 'Test Passed' : 'Test Failed'}
                >
                  {testResults['bluedart'].message}
                </Alert>
              )}

              <div className="flex gap-2 pt-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => handleSave('bluedart')}
                  loading={saving === 'bluedart'}
                >
                  Save Blue Dart
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTest('bluedart')}
                  loading={testing === 'bluedart'}
                  icon={<Zap className="h-3.5 w-3.5" />}
                >
                  Test Connection
                </Button>
              </div>
            </CardBody>
          </Card>

          {/* Xpressbees */}
          <Card>
            <CardHeader
              title="Xpressbees Logistics"
              description="E-commerce and B2B courier dispatch & AWB booking"
              icon={<Truck className="h-5 w-5 text-accent-400" />}
              actions={renderBadge(xpressbees.status, xpressbees.is_active)}
            />
            <CardBody className="space-y-4">
              <div className="flex items-center justify-between pb-2 border-b border-surface-line/60">
                <span className="text-xs text-slate-300 font-medium">Enable Xpressbees</span>
                <Switch
                  checked={xpressbees.is_active}
                  onChange={(val: boolean) => setXpressbees((p) => ({ ...p, is_active: val }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Account Email</label>
                <Input
                  type="email"
                  value={xpressbees.email}
                  placeholder="logistics@company.com"
                  onChange={(e) => setXpressbees((p) => ({ ...p, email: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">Password</label>
                <Input
                  type="password"
                  value={xpressbees.password}
                  placeholder="••••••••••••••••"
                  onChange={(e) => setXpressbees((p) => ({ ...p, password: e.target.value }))}
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-400 mb-1">API Token / Secret Key</label>
                <Input
                  type="password"
                  value={xpressbees.token}
                  placeholder="xb_token_..."
                  onChange={(e) => setXpressbees((p) => ({ ...p, token: e.target.value }))}
                />
              </div>

              {testResults['xpressbees'] && (
                <Alert
                  tone={testResults['xpressbees'].ok ? 'success' : 'danger'}
                  title={testResults['xpressbees'].ok ? 'Test Passed' : 'Test Failed'}
                >
                  {testResults['xpressbees'].message}
                </Alert>
              )}

              <div className="flex gap-2 pt-2">
                <Button
                  variant="primary"
                  size="sm"
                  onClick={() => handleSave('xpressbees')}
                  loading={saving === 'xpressbees'}
                >
                  Save Xpressbees
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => handleTest('xpressbees')}
                  loading={testing === 'xpressbees'}
                  icon={<Zap className="h-3.5 w-3.5" />}
                >
                  Test Connection
                </Button>
              </div>
            </CardBody>
          </Card>
        </div>
      )}

      {/* MEETINGS TAB */}
      {activeTab === 'meetings' && <GoogleConnectPanel tenantId={tenantId} />}
    </div>
  )
}

export default IntegrationsPanel
