import { useState } from 'react'
import {
  Plus,
  Truck,
  CreditCard,
  Settings2,
  Play,
  ExternalLink,
  ShieldCheck,
  RefreshCw,
  Zap,
} from 'lucide-react'
import {
  apiOnboarding,
  tenantIntegrationsApi,
  PAYMENT_PROVIDERS,
  SHIPPING_PROVIDERS,
  type ApiOnboardingRequest,
  type ApiOnboardingStatus,
  type ApiOnboardingType,
  type ApiProviderPreset,
  type TenantIntegration,
  type IntegrationTestResult,
} from '@/lib/api-onboarding'
import { useAsync, useAction } from '@/lib/hooks'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { useTenants } from '@/lib/tenants'
import { useAuth } from '@/lib/auth'

const STATUS_TONE: Record<ApiOnboardingStatus, 'warning' | 'success' | 'danger'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
}

const API_LABEL: Record<ApiOnboardingType, string> = {
  payment_api: 'Payment Gateway API',
  order_api: 'Order & Shipping API',
}

export function ApiOnboardingPanel() {
  const { identity } = useAuth()
  const { tenants } = useTenants()
  const tenantId = identity?.tenant_id || tenants[0]?.id || 'default'

  const state = useAsync((signal) => apiOnboarding.mine(signal), [])
  const integrationsState = useAsync((signal) => tenantIntegrationsApi.list(tenantId, signal), [tenantId])
  const action = useAction()
  const toast = useToast()

  const [activeTab, setActiveTab] = useState<'connections' | 'simulator' | 'requests'>('connections')
  const [creating, setCreating] = useState(false)
  const [apiType, setApiType] = useState<ApiOnboardingType>('payment_api')
  const [selectedPresetId, setSelectedPresetId] = useState<string>('stripe')
  const [provider, setProvider] = useState('Stripe')
  const [customProvider, setCustomProvider] = useState('')
  const [environment, setEnvironment] = useState<'sandbox' | 'production'>('sandbox')
  const [purpose, setPurpose] = useState(
    'Payment gateway integration for processing user checkout orders and automated transaction verification.',
  )

  // Configure modal/panel state
  const [configuringProvider, setConfiguringProvider] = useState<string | null>(null)
  const [credsForm, setCredsForm] = useState<Record<string, string>>({})
  const [testResult, setTestResult] = useState<IntegrationTestResult | null>(null)

  // Demo / Simulator State
  const [demoAmount, setDemoAmount] = useState<number>(499)
  const [demoOrderId, setDemoOrderId] = useState<string>(`ORD-${Math.floor(1000 + Math.random() * 9000)}`)
  const [demoPaymentResult, setDemoPaymentResult] = useState<any>(null)
  const [demoOriginPin, setDemoOriginPin] = useState('400001')
  const [demoDestPin, setDemoDestPin] = useState('110001')
  const [demoAwbResult, setDemoAwbResult] = useState<any>(null)
  const [trackingAwb, setTrackingAwb] = useState('')
  const [trackResult, setTrackResult] = useState<any>(null)

  const requests = state.data ?? []
  const configuredIntegrations: TenantIntegration[] = integrationsState.data ?? []

  const getIntegrationFor = (provName: string) =>
    configuredIntegrations.find((i) => i.provider.toLowerCase() === provName.toLowerCase())

  const openConfigModal = (provName: string) => {
    setConfiguringProvider(provName)
    setTestResult(null)
    const existing = getIntegrationFor(provName)
    setCredsForm(existing?.credentials_masked || {})
  }

  const handleSaveConfig = async (provName: string) => {
    const provLower = provName.toLowerCase()
    const isPayment = provLower.includes('stripe') || provLower.includes('razorpay') || provLower.includes('payment')
    const type: ApiOnboardingType = isPayment ? 'payment_api' : 'order_api'

    const res = await action.run(() =>
      tenantIntegrationsApi.saveConfig(tenantId, provLower, {
        api_type: type,
        environment,
        is_active: true,
        credentials: credsForm,
        webhook_secret: credsForm.webhook_secret || '',
      }),
    )
    if (res?.ok) {
      toast.push(`${provName} credentials saved`)
      integrationsState.reload()
      // Auto test connection
      handleTestConnection(provName)
    }
  }

  const handleTestConnection = async (provName: string) => {
    const provLower = provName.toLowerCase()
    const isPayment = provLower.includes('stripe') || provLower.includes('razorpay') || provLower.includes('payment')
    const type: ApiOnboardingType = isPayment ? 'payment_api' : 'order_api'

    setTestResult(null)
    const result = await action.run(() =>
      tenantIntegrationsApi.testConnection(tenantId, provLower, {
        api_type: type,
        environment,
        credentials: credsForm,
      }),
    )
    if (result) {
      setTestResult(result)
      if (result.ok) {
        toast.push(`Connected to ${provName} successfully!`)
      } else {
        toast.push(result.details?.error || 'Connection failed', 'error')
      }
      integrationsState.reload()
    }
  }

  const handleCreateTestPayment = async (provName: string) => {
    setDemoPaymentResult(null)
    const res = await action.run(() =>
      tenantIntegrationsApi.createPaymentSession(tenantId, {
        order_id: demoOrderId,
        amount: Number(demoAmount) || 100,
        currency: 'INR',
        provider: provName.toLowerCase(),
        description: 'Demo WhatsApp Checkout Payment',
        customer_phone: '919876543210',
        customer_name: 'Test Customer',
      }),
    )
    if (res?.ok) {
      setDemoPaymentResult(res)
      toast.push('Test payment link created!')
    }
  }

  const handleBookTestShipment = async (provName: string) => {
    setDemoAwbResult(null)
    const res = await action.run(() =>
      tenantIntegrationsApi.bookShipment(tenantId, {
        order_id: demoOrderId,
        provider: provName.toLowerCase(),
        origin_pincode: demoOriginPin,
        destination_pincode: demoDestPin,
        customer_name: 'John Doe',
        customer_phone: '919876543210',
        weight_kg: 0.5,
      }),
    )
    if (res?.ok) {
      setDemoAwbResult(res)
      setTrackingAwb(res.awb_number)
      toast.push(`AWB Generated: ${res.awb_number}`)
    }
  }

  const handleTrackAwb = async () => {
    if (!trackingAwb) return
    const res = await action.run(() => tenantIntegrationsApi.trackShipment(tenantId, trackingAwb))
    if (res) {
      setTrackResult(res)
      toast.push(`Shipment Status: ${res.status}`)
    }
  }

  const handleSelectPreset = (preset: ApiProviderPreset) => {
    setApiType(preset.apiType)
    setSelectedPresetId(preset.id)
    if (preset.isCustom) {
      setProvider('')
      setCustomProvider('')
      setPurpose(
        preset.apiType === 'payment_api'
          ? 'Custom payment gateway integration for handling transaction processing and checkout.'
          : 'Custom logistics and order shipping API integration for order fulfillment.',
      )
    } else {
      setProvider(preset.name)
      setCustomProvider('')
      if (preset.id === 'stripe') {
        setPurpose('Stripe payment gateway integration for processing credit cards, Apple Pay and online checkout.')
      } else if (preset.id === 'razorpay') {
        setPurpose('Razorpay payment gateway integration for processing UPI, NetBanking, Cards and online payments.')
      } else if (preset.id === 'bluedart') {
        setPurpose('Blue Dart express logistics integration for automated shipment dispatch and AWB tracking.')
      } else if (preset.id === 'xpressbees') {
        setPurpose('Xpressbees courier delivery integration for automated order shipping, package tracking, and COD.')
      }
    }
  }

  const submit = async () => {
    const finalProviderName = selectedPresetId.includes('custom')
      ? customProvider.trim() || 'Custom Provider'
      : provider.trim()

    const result = await action.run(() =>
      apiOnboarding.create({
        api_type: apiType,
        provider: finalProviderName,
        environment,
        purpose: purpose.trim(),
      }),
    )
    if (result) {
      toast.push(`${API_LABEL[result.api_type as ApiOnboardingType]} request submitted for ${finalProviderName}`)
      setCreating(false)
      setProvider('')
      setCustomProvider('')
      setPurpose('')
      state.reload()
    }
  }

  const activePresets = apiType === 'payment_api' ? PAYMENT_PROVIDERS : SHIPPING_PROVIDERS

  return (
    <div className="space-y-6">
      <PageHeader
        title="API Access & Live Integrations"
        description="Connect real Payment Gateways (Stripe, Razorpay, Custom) and Shipping Logistics (Blue Dart, Xpressbees, Custom) to your WhatsApp bot."
        actions={
          <div className="flex gap-2">
            <Button
              variant={activeTab === 'connections' ? 'primary' : 'ghost'}
              onClick={() => setActiveTab('connections')}
              icon={<Zap className="h-4 w-4" />}
            >
              Live Providers
            </Button>
            <Button
              variant={activeTab === 'simulator' ? 'primary' : 'ghost'}
              onClick={() => setActiveTab('simulator')}
              icon={<Play className="h-4 w-4" />}
            >
              Test Simulator
            </Button>
            <Button
              variant={activeTab === 'requests' ? 'primary' : 'ghost'}
              onClick={() => setActiveTab('requests')}
              icon={<Plus className="h-4 w-4" />}
            >
              Requests ({requests.length})
            </Button>
          </div>
        }
      />

      {/* TAB 1: LIVE PROVIDERS & CREDENTIAL CONFIGURATION */}
      {activeTab === 'connections' && (
        <div className="space-y-6">
          {/* Payment Gateways Section */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                <CreditCard className="h-5 w-5 text-emerald-400" />
                Payment Gateways (Stripe · Razorpay · Custom)
              </h2>
              <Badge tone="accent">Checkout & UPI</Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              {/* Stripe Card */}
              <ProviderConfigCard
                icon="💳"
                name="Stripe"
                category="Credit Cards, Apple Pay, Global Currencies"
                integration={getIntegrationFor('stripe')}
                onConfigure={() => openConfigModal('stripe')}
                onTest={() => handleTestConnection('stripe')}
                busy={action.busy}
              />

              {/* Razorpay Card */}
              <ProviderConfigCard
                icon="⚡"
                name="Razorpay"
                category="UPI, NetBanking, Cards, Wallets, EMI"
                integration={getIntegrationFor('razorpay')}
                onConfigure={() => openConfigModal('razorpay')}
                onTest={() => handleTestConnection('razorpay')}
                busy={action.busy}
              />

              {/* Custom Payment Card */}
              <ProviderConfigCard
                icon="🔧"
                name="Custom Payment Gateway"
                category="Any Custom Payment API or Webhook"
                integration={getIntegrationFor('custom_payment') || getIntegrationFor('custom')}
                onConfigure={() => openConfigModal('custom_payment')}
                onTest={() => handleTestConnection('custom_payment')}
                busy={action.busy}
              />
            </div>
          </div>

          {/* Delivery & Shipping Section */}
          <div>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                <Truck className="h-5 w-5 text-blue-400" />
                Logistics & Delivery Carriers (Blue Dart · Xpressbees · Custom)
              </h2>
              <Badge tone="accent">AWB & Real Tracking</Badge>
            </div>

            <div className="grid gap-4 sm:grid-cols-3">
              {/* Blue Dart Card */}
              <ProviderConfigCard
                icon="🚚"
                name="Blue Dart"
                category="Express Air Courier & AWB Tracking"
                integration={getIntegrationFor('bluedart') || getIntegrationFor('blue_dart')}
                onConfigure={() => openConfigModal('bluedart')}
                onTest={() => handleTestConnection('bluedart')}
                busy={action.busy}
              />

              {/* Xpressbees Card */}
              <ProviderConfigCard
                icon="📦"
                name="Xpressbees"
                category="E-Commerce Logistics & COD Tracking"
                integration={getIntegrationFor('xpressbees')}
                onConfigure={() => openConfigModal('xpressbees')}
                onTest={() => handleTestConnection('xpressbees')}
                busy={action.busy}
              />

              {/* Custom Shipping Card */}
              <ProviderConfigCard
                icon="🛠️"
                name="Custom Shipping Provider"
                category="Custom Courier Dispatch & Tracking API"
                integration={getIntegrationFor('custom_shipping')}
                onConfigure={() => openConfigModal('custom_shipping')}
                onTest={() => handleTestConnection('custom_shipping')}
                busy={action.busy}
              />
            </div>
          </div>

          {/* CREDENTIALS CONFIGURATION MODAL / DRAWER */}
          {configuringProvider && (
            <Card className="border-indigo-500/50 bg-slate-900/90 shadow-xl">
              <CardHeader
                title={`Configure & Connect ${configuringProvider.toUpperCase()}`}
                description="Set your API keys, credentials, and webhook secrets. Test connectivity live before saving."
                actions={
                  <Button variant="ghost" onClick={() => setConfiguringProvider(null)}>
                    Close
                  </Button>
                }
              />
              <CardBody className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Select
                    label="Environment"
                    value={environment}
                    onChange={(e) => setEnvironment(e.target.value as any)}
                  >
                    <option value="sandbox">Sandbox / Test Mode (Recommended for testing)</option>
                    <option value="production">Production Live Mode</option>
                  </Select>
                </div>

                {/* STRIPE FIELDS */}
                {configuringProvider.includes('stripe') && (
                  <div className="space-y-3">
                    <Input
                      label="Stripe Secret Key (sk_test_... or sk_live_...)"
                      placeholder="sk_test_51Mz..."
                      type="password"
                      value={credsForm.secret_key || credsForm.api_key || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, secret_key: e.target.value })}
                      hint="Found in your Stripe Dashboard → Developers → API keys."
                    />
                    <Input
                      label="Stripe Publishable Key (pk_test_...)"
                      placeholder="pk_test_51Mz..."
                      value={credsForm.publishable_key || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, publishable_key: e.target.value })}
                    />
                    <Input
                      label="Stripe Webhook Secret (whsec_...)"
                      placeholder="whsec_..."
                      type="password"
                      value={credsForm.webhook_secret || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, webhook_secret: e.target.value })}
                      hint="Webhook endpoint URL: /api/webhooks/payments/{tenant_id}/stripe"
                    />
                  </div>
                )}

                {/* RAZORPAY FIELDS */}
                {configuringProvider.includes('razorpay') && (
                  <div className="space-y-3">
                    <Input
                      label="Razorpay Key ID (rzp_test_... or rzp_live_...)"
                      placeholder="rzp_test_1DP5mmOlF5G5ag"
                      value={credsForm.key_id || credsForm.api_key || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, key_id: e.target.value })}
                      hint="Found in Razorpay Dashboard → Settings → API Keys."
                    />
                    <Input
                      label="Razorpay Key Secret"
                      placeholder="Enter Razorpay Key Secret"
                      type="password"
                      value={credsForm.key_secret || credsForm.secret || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, key_secret: e.target.value })}
                    />
                    <Input
                      label="Razorpay Webhook Secret"
                      placeholder="Optional Webhook Secret"
                      type="password"
                      value={credsForm.webhook_secret || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, webhook_secret: e.target.value })}
                    />
                  </div>
                )}

                {/* BLUE DART FIELDS */}
                {configuringProvider.includes('bluedart') && (
                  <div className="space-y-3">
                    <Input
                      label="Blue Dart Customer Code"
                      placeholder="e.g. 123456"
                      value={credsForm.customer_code || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, customer_code: e.target.value })}
                    />
                    <Input
                      label="Blue Dart License Key"
                      placeholder="Enter Blue Dart License Key"
                      type="password"
                      value={credsForm.license_key || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, license_key: e.target.value })}
                    />
                    <Input
                      label="Blue Dart Login ID"
                      placeholder="e.g. BD_USER"
                      value={credsForm.login_id || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, login_id: e.target.value })}
                    />
                  </div>
                )}

                {/* XPRESSBEES FIELDS */}
                {configuringProvider.includes('xpressbees') && (
                  <div className="space-y-3">
                    <Input
                      label="Xpressbees Account Email"
                      placeholder="merchant@example.com"
                      value={credsForm.email || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, email: e.target.value })}
                    />
                    <Input
                      label="Xpressbees Password"
                      type="password"
                      placeholder="••••••••"
                      value={credsForm.password || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, password: e.target.value })}
                    />
                    <Input
                      label="Or Xpressbees API Token"
                      placeholder="Bearer token if using static token"
                      type="password"
                      value={credsForm.token || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, token: e.target.value })}
                    />
                  </div>
                )}

                {/* CUSTOM PROVIDER FIELDS */}
                {configuringProvider.includes('custom') && (
                  <div className="space-y-3">
                    <Input
                      label="Custom API Endpoint URL"
                      placeholder="https://api.mygateway.com/v1/checkout"
                      value={credsForm.endpoint_url || credsForm.api_url || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, endpoint_url: e.target.value })}
                      hint="Must start with http:// or https://"
                    />
                    <Input
                      label="Authorization Header / Bearer Token"
                      placeholder="Bearer your_secret_token"
                      value={credsForm.auth_header || credsForm.api_key || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, auth_header: e.target.value })}
                    />
                    <Input
                      label="Webhook Signing Secret"
                      placeholder="Secret for signature verification"
                      type="password"
                      value={credsForm.webhook_secret || ''}
                      onChange={(e) => setCredsForm({ ...credsForm, webhook_secret: e.target.value })}
                    />
                  </div>
                )}

                {/* Test Result Box */}
                {testResult && (
                  <Alert
                    tone={testResult.ok ? 'success' : 'danger'}
                    title={testResult.ok ? '✅ Connection Test Passed' : '❌ Connection Test Failed'}
                  >
                    {testResult.details?.message || testResult.details?.error || JSON.stringify(testResult.details)}
                  </Alert>
                )}

                <div className="flex gap-2 pt-2">
                  <Button
                    variant="primary"
                    loading={action.busy}
                    onClick={() => handleSaveConfig(configuringProvider)}
                    icon={<ShieldCheck className="h-4 w-4" />}
                  >
                    Save & Verify Connection
                  </Button>
                  <Button
                    variant="ghost"
                    loading={action.busy}
                    onClick={() => handleTestConnection(configuringProvider)}
                    icon={<RefreshCw className="h-4 w-4" />}
                  >
                    Test Live Connection
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      )}

      {/* TAB 2: LIVE TEST SIMULATOR */}
      {activeTab === 'simulator' && (
        <div className="grid gap-6 sm:grid-cols-2">
          {/* Payment Link Tester */}
          <Card className="border-emerald-500/30">
            <CardHeader
              title="Payment Checkout Simulator"
              description="Generate a real checkout link using Stripe, Razorpay, or Custom to test WhatsApp order checkout."
              icon={<CreditCard className="h-5 w-5 text-emerald-400" />}
            />
            <CardBody className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label="Order ID"
                  value={demoOrderId}
                  onChange={(e) => setDemoOrderId(e.target.value)}
                />
                <Input
                  label="Amount (INR ₹)"
                  type="number"
                  value={String(demoAmount)}
                  onChange={(e) => setDemoAmount(Number(e.target.value) || 0)}
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  loading={action.busy}
                  onClick={() => handleCreateTestPayment('stripe')}
                >
                  💳 Test with Stripe
                </Button>
                <Button
                  variant="primary"
                  loading={action.busy}
                  onClick={() => handleCreateTestPayment('razorpay')}
                >
                  ⚡ Test with Razorpay
                </Button>
                <Button
                  variant="ghost"
                  loading={action.busy}
                  onClick={() => handleCreateTestPayment('custom_payment')}
                >
                  🔧 Test with Custom
                </Button>
              </div>

              {demoPaymentResult && (
                <div className="rounded-lg border border-emerald-500/40 bg-emerald-950/30 p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase text-emerald-300">
                      Payment Link Generated ({demoPaymentResult.provider})
                    </span>
                    <Badge tone="success">Active</Badge>
                  </div>
                  <div className="text-xs text-slate-300 font-mono break-all bg-slate-900/80 p-2 rounded">
                    {demoPaymentResult.payment_url || 'No URL returned'}
                  </div>
                  {demoPaymentResult.payment_url && (
                    <a
                      href={demoPaymentResult.payment_url}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 text-xs text-emerald-400 font-semibold hover:underline mt-1"
                    >
                      Open Live Checkout Page <ExternalLink className="h-3.5 w-3.5" />
                    </a>
                  )}
                </div>
              )}
            </CardBody>
          </Card>

          {/* Shipping & AWB Tester */}
          <Card className="border-blue-500/30">
            <CardHeader
              title="Shipping & AWB Tracking Simulator"
              description="Book express shipment with Blue Dart or Xpressbees and track live parcel status."
              icon={<Truck className="h-5 w-5 text-blue-400" />}
            />
            <CardBody className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <Input
                  label="Origin Pincode"
                  value={demoOriginPin}
                  onChange={(e) => setDemoOriginPin(e.target.value)}
                />
                <Input
                  label="Destination Pincode"
                  value={demoDestPin}
                  onChange={(e) => setDemoDestPin(e.target.value)}
                />
              </div>

              <div className="flex flex-wrap gap-2">
                <Button
                  variant="primary"
                  loading={action.busy}
                  onClick={() => handleBookTestShipment('bluedart')}
                >
                  🚚 Book with Blue Dart
                </Button>
                <Button
                  variant="primary"
                  loading={action.busy}
                  onClick={() => handleBookTestShipment('xpressbees')}
                >
                  📦 Book with Xpressbees
                </Button>
              </div>

              {demoAwbResult && (
                <div className="rounded-lg border border-blue-500/40 bg-blue-950/30 p-4 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-semibold uppercase text-blue-300">
                      AWB Generated: {demoAwbResult.awb_number} ({demoAwbResult.provider})
                    </span>
                    <Badge tone="accent">Booked</Badge>
                  </div>
                  <div className="flex gap-2">
                    <Button variant="ghost" className="text-xs" onClick={handleTrackAwb}>
                      Track Live Status
                    </Button>
                    {demoAwbResult.tracking_url && (
                      <a
                        href={demoAwbResult.tracking_url}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1 text-xs text-blue-400 font-semibold hover:underline"
                      >
                        Carrier Portal <ExternalLink className="h-3.5 w-3.5" />
                      </a>
                    )}
                  </div>
                </div>
              )}

              {trackResult && (
                <div className="rounded-lg border border-slate-800 bg-slate-900/80 p-3 space-y-1 text-xs">
                  <div className="font-semibold text-slate-200">
                    Carrier: {trackResult.carrier} · Status: <span className="text-emerald-400">{trackResult.status}</span>
                  </div>
                  <div className="text-slate-400">AWB: {trackResult.awb}</div>
                </div>
              )}
            </CardBody>
          </Card>
        </div>
      )}

      {/* TAB 3: REQUESTS & APPROVAL QUEUE */}
      {activeTab === 'requests' && (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-slate-400">
              Submitted Integration Requests ({requests.length})
            </h3>
            {!creating && (
              <Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setCreating(true)}>
                New Request
              </Button>
            )}
          </div>

          {creating && (
            <Card className="border-indigo-500/30">
              <CardHeader
                title="Request New Integration Access"
                description="Select provider and submit for superadmin approval."
              />
              <CardBody className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Select
                    label="Integration Category"
                    value={apiType}
                    onChange={(event) => {
                      const newType = event.target.value as ApiOnboardingType
                      setApiType(newType)
                      const presets = newType === 'payment_api' ? PAYMENT_PROVIDERS : SHIPPING_PROVIDERS
                      handleSelectPreset(presets[0])
                    }}
                  >
                    <option value="payment_api">💳 Payment Gateway API</option>
                    <option value="order_api">🚚 Delivery & Shipping API</option>
                  </Select>

                  <Select
                    label="Choose Integration Provider"
                    value={selectedPresetId}
                    onChange={(event) => {
                      const found = activePresets.find((p) => p.id === event.target.value)
                      if (found) handleSelectPreset(found)
                    }}
                  >
                    {apiType === 'payment_api' ? (
                      <>
                        <option value="stripe">💳 Stripe (Global Cards, Apple Pay, Subscriptions)</option>
                        <option value="razorpay">⚡ Razorpay (UPI, NetBanking, Cards, Wallets)</option>
                        <option value="custom_payment">🔧 Custom Payment Gateway (Specify your own)</option>
                      </>
                    ) : (
                      <>
                        <option value="bluedart">🚚 Blue Dart (Express Air Logistics & AWB Tracking)</option>
                        <option value="xpressbees">📦 Xpressbees (E-Commerce Logistics & COD Delivery)</option>
                        <option value="custom_shipping">🛠️ Custom Courier / Delivery Provider (Specify your own)</option>
                      </>
                    )}
                  </Select>
                </div>

                {selectedPresetId.includes('custom') && (
                  <Input
                    label="Custom Provider Name"
                    placeholder="e.g. PayPal, FedEx, Delhivery..."
                    value={customProvider}
                    onChange={(e) => {
                      setCustomProvider(e.target.value)
                      setProvider(e.target.value)
                    }}
                  />
                )}

                <Textarea
                  label="Business Purpose"
                  value={purpose}
                  rows={3}
                  onChange={(e) => setPurpose(e.target.value)}
                />

                <div className="flex gap-2">
                  <Button
                    variant="primary"
                    loading={action.busy}
                    disabled={purpose.trim().length < 10}
                    onClick={submit}
                  >
                    Submit Request
                  </Button>
                  <Button variant="ghost" onClick={() => setCreating(false)}>
                    Cancel
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}

          {requests.map((req) => (
            <RequestCard key={req.id} request={req} />
          ))}
        </div>
      )}
    </div>
  )
}

function ProviderConfigCard({
  icon,
  name,
  category,
  integration,
  onConfigure,
  onTest,
  busy,
}: {
  icon: string
  name: string
  category: string
  integration?: TenantIntegration
  onConfigure: () => void
  onTest: () => void
  busy: boolean
}) {
  const isVerified = integration?.status === 'verified'
  const isConfigured = integration?.status === 'configured'
  const isError = integration?.status === 'error'

  return (
    <Card className={`border transition-all ${isVerified ? 'border-emerald-500/50 bg-emerald-950/10' : 'border-slate-800 bg-slate-900/40'}`}>
      <CardBody className="space-y-3">
        <div className="flex items-center justify-between">
          <span className="text-2xl">{icon}</span>
          {isVerified ? (
            <Badge tone="success">Connected ✅</Badge>
          ) : isConfigured ? (
            <Badge tone="accent">Configured ⚙️</Badge>
          ) : isError ? (
            <Badge tone="danger">Connection Error ❌</Badge>
          ) : (
            <Badge tone="muted">Not Configured</Badge>
          )}
        </div>

        <div>
          <div className="font-semibold text-slate-100">{name}</div>
          <div className="text-xs text-slate-400">{category}</div>
        </div>

        {integration?.last_tested_at && (
          <div className="text-[11px] text-slate-500">
            Last verified: {formatDate(integration.last_tested_at)}
          </div>
        )}

        <div className="flex gap-2 pt-1">
          <Button
            variant="primary"
            className="flex-1 text-xs"
            icon={<Settings2 className="h-3.5 w-3.5" />}
            onClick={onConfigure}
          >
            Configure
          </Button>
          {integration?.has_credentials && (
            <Button
              variant="ghost"
              className="text-xs"
              loading={busy}
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              onClick={onTest}
            >
              Test
            </Button>
          )}
        </div>
      </CardBody>
    </Card>
  )
}

function RequestCard({ request }: { request: ApiOnboardingRequest }) {
  const providerLower = (request.provider || '').toLowerCase()
  const isStripe = providerLower.includes('stripe')
  const isRazorpay = providerLower.includes('razorpay')
  const isBlueDart = providerLower.includes('blue') || providerLower.includes('dart')
  const isXpressbees = providerLower.includes('xpress') || providerLower.includes('bees')

  const icon = isStripe ? (
    <span className="text-lg">💳</span>
  ) : isRazorpay ? (
    <span className="text-lg">⚡</span>
  ) : isBlueDart ? (
    <span className="text-lg">🚚</span>
  ) : isXpressbees ? (
    <span className="text-lg">📦</span>
  ) : request.api_type === 'payment_api' ? (
    <CreditCard className="h-4 w-4 text-emerald-400" />
  ) : (
    <Truck className="h-4 w-4 text-blue-400" />
  )

  return (
    <Card>
      <CardHeader
        title={`${API_LABEL[request.api_type]}${request.provider ? ` · ${request.provider}` : ''}`}
        description={`Submitted ${formatDate(request.created_at)} · ${request.environment.toUpperCase()} mode`}
        icon={icon}
        actions={<Badge tone={STATUS_TONE[request.status]}>{request.status}</Badge>}
      />
      <CardBody className="space-y-3">
        <p className="whitespace-pre-wrap text-sm leading-relaxed text-slate-300">{request.purpose}</p>
        {request.status === 'approved' ? (
          <Alert tone="success" title="Approved & Ready">
            Approved by {request.reviewer_username || 'a superadmin'}. You can now configure credentials in the Live Providers tab.
          </Alert>
        ) : request.status === 'rejected' ? (
          <Alert tone="danger" title="Request rejected">
            {request.decision_note || 'No additional note was provided.'}
          </Alert>
        ) : (
          <Alert tone="info" title="Awaiting review">
            This request is pending review by a superadmin.
          </Alert>
        )}
      </CardBody>
    </Card>
  )
}
