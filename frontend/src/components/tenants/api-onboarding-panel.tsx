import { useState } from 'react'
import { Plus, CheckCircle2, Truck, CreditCard } from 'lucide-react'
import {
  apiOnboarding,
  PAYMENT_PROVIDERS,
  SHIPPING_PROVIDERS,
  type ApiOnboardingRequest,
  type ApiOnboardingStatus,
  type ApiOnboardingType,
  type ApiProviderPreset,
} from '@/lib/api-onboarding'
import { useAsync, useAction } from '@/lib/hooks'
import { formatDate } from '@/lib/format'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'

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
  const state = useAsync((signal) => apiOnboarding.mine(signal), [])
  const action = useAction()
  const toast = useToast()
  const [creating, setCreating] = useState(false)
  const [apiType, setApiType] = useState<ApiOnboardingType>('payment_api')
  const [selectedPresetId, setSelectedPresetId] = useState<string>('stripe')
  const [provider, setProvider] = useState('Stripe')
  const [customProvider, setCustomProvider] = useState('')
  const [environment, setEnvironment] = useState<'sandbox' | 'production'>('sandbox')
  const [purpose, setPurpose] = useState(
    'Payment gateway integration for processing user checkout orders and automated transaction verification.',
  )

  // Tenant's active preferred selections
  const [activePaymentProvider, setActivePaymentProvider] = useState<string>('Stripe')
  const [activeShippingProvider, setActiveShippingProvider] = useState<string>('Blue Dart')

  const requests = state.data ?? []

  const isProviderRequested = (type: ApiOnboardingType, providerName: string) =>
    requests.some(
      (request: ApiOnboardingRequest) =>
        request.api_type === type &&
        request.provider.toLowerCase() === providerName.toLowerCase() &&
        request.status !== 'rejected',
    )

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
    <div>
      <PageHeader
        title="API Access & Integrations"
        description="Choose payment and delivery integration choices (Stripe, Razorpay, Blue Dart, Xpressbees, or Custom) and request superadmin review."
        actions={
          !creating && (
            <Button
              variant="primary"
              icon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setCreating(true)
              }}
            >
              Request New Integration
            </Button>
          )
        }
      />

      {/* Integration Choice Cards */}
      <div className="mb-6 grid gap-5 sm:grid-cols-2">
        {/* Payment Integration Choice Card */}
        <Card className="border-emerald-500/30 bg-emerald-950/10">
          <CardHeader
            title="Payment Integration Choice"
            description="Select which payment gateway provider you want connected for checkout"
            icon={<CreditCard className="h-5 w-5 text-emerald-400" />}
          />
          <CardBody className="space-y-4 pt-0">
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-300">Choose Active Payment Provider:</label>
              <div className="grid gap-2">
                {[
                  { id: 'Stripe', label: '💳 Stripe', desc: 'Credit Cards, Apple Pay, International' },
                  { id: 'Razorpay', label: '⚡ Razorpay', desc: 'UPI, NetBanking, Cards, Wallets' },
                  { id: 'Custom Payment', label: '🔧 Custom Payment Gateway', desc: 'Custom gateway provider API' },
                ].map((item) => {
                  const isChecked = activePaymentProvider === item.id
                  const isApproved = requests.some(
                    (r) => r.api_type === 'payment_api' && r.provider.toLowerCase().includes(item.id.toLowerCase().split(' ')[0]) && r.status === 'approved',
                  )
                  return (
                    <div
                      key={item.id}
                      onClick={() => {
                        setActivePaymentProvider(item.id)
                        toast.push(`Selected ${item.id} as active payment integration choice`)
                      }}
                      className={`cursor-pointer rounded-lg border p-3 transition-all ${
                        isChecked
                          ? 'border-emerald-400 bg-emerald-950/40 ring-1 ring-emerald-400'
                          : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-semibold text-slate-100">{item.label}</div>
                        <div className="flex items-center gap-2">
                          {isApproved && <Badge tone="success">Approved</Badge>}
                          {isChecked && <CheckCircle2 className="h-4 w-4 text-emerald-400" />}
                        </div>
                      </div>
                      <div className="mt-1 text-xs text-slate-400">{item.desc}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          </CardBody>
        </Card>

        {/* Delivery Integration Choice Card */}
        <Card className="border-blue-500/30 bg-blue-950/10">
          <CardHeader
            title="Delivery & Logistics Choice"
            description="Select which shipping provider you want connected for fulfillment"
            icon={<Truck className="h-5 w-5 text-blue-400" />}
          />
          <CardBody className="space-y-4 pt-0">
            <div className="space-y-2">
              <label className="text-xs font-medium text-slate-300">Choose Active Delivery Provider:</label>
              <div className="grid gap-2">
                {[
                  { id: 'Blue Dart', label: '🚚 Blue Dart', desc: 'Express Air Courier & AWB Tracking' },
                  { id: 'Xpressbees', label: '📦 Xpressbees', desc: 'E-Commerce Logistics & COD Support' },
                  { id: 'Custom Delivery', label: '🛠️ Custom Shipping Provider', desc: 'Custom courier or logistics provider' },
                ].map((item) => {
                  const isChecked = activeShippingProvider === item.id
                  const isApproved = requests.some(
                    (r) => r.api_type === 'order_api' && r.provider.toLowerCase().includes(item.id.toLowerCase().split(' ')[0]) && r.status === 'approved',
                  )
                  return (
                    <div
                      key={item.id}
                      onClick={() => {
                        setActiveShippingProvider(item.id)
                        toast.push(`Selected ${item.id} as active delivery integration choice`)
                      }}
                      className={`cursor-pointer rounded-lg border p-3 transition-all ${
                        isChecked
                          ? 'border-blue-400 bg-blue-950/40 ring-1 ring-blue-400'
                          : 'border-slate-800 bg-slate-900/40 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className="font-semibold text-slate-100">{item.label}</div>
                        <div className="flex items-center gap-2">
                          {isApproved && <Badge tone="success">Approved</Badge>}
                          {isChecked && <CheckCircle2 className="h-4 w-4 text-blue-400" />}
                        </div>
                      </div>
                      <div className="mt-1 text-xs text-slate-400">{item.desc}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          </CardBody>
        </Card>
      </div>

      <Alert tone="warning" title="Do not enter API secrets or keys" className="mb-6">
        This request form must not contain API keys, passwords, tokens, or live secrets. Approval grants eligibility only; credentials are configured securely after approval.
      </Alert>

      {/* Integration Request Form */}
      {creating && (
        <Card className="mb-6 border-indigo-500/30">
          <CardHeader
            title="Request New Integration Access"
            description="Select your desired provider (Stripe, Razorpay, Blue Dart, Xpressbees, or Custom) and submit for superadmin review."
          />
          <CardBody className="space-y-5">
            {/* Category & Provider Selectors */}
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

            {/* Quick Pick Cards */}
            <div>
              <label className="mb-2 block text-xs font-semibold uppercase tracking-wider text-slate-400">
                Or Quick Pick Provider
              </label>
              <div className="grid gap-3 sm:grid-cols-3">
                {activePresets.map((preset) => {
                  const isSelected = selectedPresetId === preset.id
                  const requested = isProviderRequested(preset.apiType, preset.name)
                  return (
                    <div
                      key={preset.id}
                      className={`cursor-pointer rounded-xl border p-3 transition-all ${
                        isSelected
                          ? 'border-indigo-400 bg-indigo-950/40 shadow-sm ring-1 ring-indigo-400'
                          : 'border-slate-800 bg-slate-900/50 hover:border-slate-700'
                      }`}
                      onClick={() => handleSelectPreset(preset)}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xl">{preset.icon}</span>
                        <div className="flex items-center gap-1">
                          {requested && <Badge tone="warning">Requested</Badge>}
                          {isSelected && <CheckCircle2 className="h-4 w-4 text-indigo-400" />}
                        </div>
                      </div>
                      <div className="mt-2 font-semibold text-slate-200">{preset.name}</div>
                      <p className="mt-1 text-xs text-slate-400 line-clamp-2">{preset.description}</p>
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Custom Provider Name Input */}
            {selectedPresetId.includes('custom') && (
              <Input
                label="Custom Provider Name"
                placeholder={
                  apiType === 'payment_api'
                    ? 'e.g. PayPal, Paytm, PhonePe, Adyen, Authorize.net...'
                    : 'e.g. DHL, FedEx, Delhivery, Shadowfax, Dunzo...'
                }
                value={customProvider}
                maxLength={100}
                onChange={(event) => {
                  setCustomProvider(event.target.value)
                  setProvider(event.target.value)
                }}
                hint="Enter the name of your custom payment gateway or delivery courier provider."
              />
            )}

            <div className="grid gap-4 sm:grid-cols-2">
              <Select
                label="Environment Requested"
                value={environment}
                onChange={(event) => setEnvironment(event.target.value as 'sandbox' | 'production')}
              >
                <option value="sandbox">Sandbox / Test Environment</option>
                <option value="production">Production Environment</option>
              </Select>

              <Input
                label="Selected Provider Name"
                value={selectedPresetId.includes('custom') ? customProvider : provider}
                readOnly={!selectedPresetId.includes('custom')}
                onChange={(event) => setProvider(event.target.value)}
                hint="Provider name submitted with the request."
              />
            </div>

            <Textarea
              label="Business Use & Integration Purpose"
              rows={3}
              value={purpose}
              maxLength={2000}
              onChange={(event) => setPurpose(event.target.value)}
              hint="Explain how your tenant will use this API integration (10–2,000 characters). Do not paste credentials."
            />

            {action.error && <Alert tone="danger" title="Could not submit request">{action.error}</Alert>}

            <div className="flex gap-2 pt-2">
              <Button
                variant="primary"
                loading={action.busy}
                disabled={purpose.trim().length < 10 || (selectedPresetId.includes('custom') && !customProvider.trim())}
                onClick={submit}
              >
                Submit Integration Request
              </Button>
              <Button variant="ghost" onClick={() => setCreating(false)}>
                Cancel
              </Button>
            </div>
          </CardBody>
        </Card>
      )}

      {state.loading && <LoadingBlock label="Loading API requests…" />}
      {state.error && <Alert tone="danger" title="Could not load API requests">{state.error}</Alert>}

      {requests.length === 0 && !state.loading && (
        <Card>
          <EmptyState
            title="No API Access Requests"
            description="Submit a request for Stripe, Razorpay, Blue Dart, Xpressbees, or your custom integration provider."
          />
        </Card>
      )}

      {requests.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wider text-slate-400">
            <span>Submitted Integration Requests ({requests.length})</span>
            <Button variant="ghost" className="text-xs" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setCreating(true)}>
              Add Another Request
            </Button>
          </div>
          {requests.map((request: ApiOnboardingRequest) => (
            <RequestCard key={request.id} request={request} />
          ))}
        </div>
      )}
    </div>
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
          <Alert tone="success" title={request.eligible ? 'Eligible — setup required' : 'Approved — setup required'}>
            Approved by {request.reviewer_username || 'a superadmin'}{request.decided_at ? ` on ${formatDate(request.decided_at)}` : ''}. Configure credentials through the secure setup process before enabling live API traffic.
          </Alert>
        ) : request.status === 'rejected' ? (
          <Alert tone="danger" title="Request rejected">
            {request.decision_note || 'No additional note was provided.'}
          </Alert>
        ) : (
          <Alert tone="info" title="Awaiting superadmin review">
            This request is pending review by a superadmin.
          </Alert>
        )}
      </CardBody>
    </Card>
  )
}
