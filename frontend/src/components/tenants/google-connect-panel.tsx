import { useEffect, useState, useCallback } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardHeader, CardBody } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, LoadingBlock } from '@/components/ui/feedback'
import { Video, RefreshCw, ExternalLink, ShieldCheck } from 'lucide-react'
import { useToast } from '@/components/ui/toast'
import { PageHeader } from '@/components/layout/page-header'

export interface GoogleConnectPanelProps {
  tenantId: string
}

interface ConnectionStatus {
  connected: boolean
  has_refresh_token?: boolean
  token_expired?: boolean
  scope?: string
}

export function GoogleConnectPanel({ tenantId }: GoogleConnectPanelProps) {
  const { push: showToast } = useToast()
  const [status, setStatus] = useState<ConnectionStatus | null>(null)
  const [loading, setLoading] = useState(true)
  const [isConnecting, setIsConnecting] = useState(false)

  const fetchStatus = useCallback(async () => {
    if (!tenantId) return
    try {
      setLoading(true)
      const resp = await fetch(`/api/tenants/${tenantId}/google-connect/status`)
      if (resp.ok) {
        const data = await resp.json()
        setStatus(data)
      } else {
        setStatus({ connected: false })
      }
    } catch (err) {
      console.error('Failed to fetch Google connection status:', err)
      setStatus({ connected: false })
    } finally {
      setLoading(false)
    }
  }, [tenantId])

  useEffect(() => {
    fetchStatus()

    const urlParams = new URLSearchParams(window.location.search)
    if (urlParams.get('success') === 'true') {
      showToast('Google Account connected successfully!', 'success')
      window.history.replaceState({}, '', window.location.pathname)
      fetchStatus()
    } else if (urlParams.get('error')) {
      showToast(`OAuth connection error: ${urlParams.get('error')}`, 'error')
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [fetchStatus, showToast])

  const handleConnectGoogle = async () => {
    if (!tenantId) return
    try {
      setIsConnecting(true)
      const resp = await fetch(`/api/tenants/${tenantId}/google-connect/oauth-url`)
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || 'Failed to generate OAuth URL')
      }
      const { oauth_url } = await resp.json()
      window.location.href = oauth_url
    } catch (err) {
      showToast(err instanceof Error ? err.message : 'Failed to start OAuth flow', 'error')
      setIsConnecting(false)
    }
  }

  const isConnected = Boolean(status?.connected && !status?.token_expired)
  const isExpired = Boolean(status?.connected && status?.token_expired && !status?.has_refresh_token)

  return (
    <div className="space-y-6">
      <PageHeader
        title="Google Calendar & Meet"
        description="Connect your business Google Workspace account to generate Google Meet links automatically for callback appointments."
      />

      <Card>
        <CardHeader
          title="Google Meet Integration"
          description="Enables automated video meeting scheduling on WhatsApp callback flows."
          icon={<Video className="h-5 w-5" />}
          actions={
            !loading && (
              <Badge tone={isConnected ? 'success' : isExpired ? 'warning' : 'neutral'}>
                {isConnected ? 'Connected' : isExpired ? 'Token Expired' : 'Not Connected'}
              </Badge>
            )
          }
        />

        <CardBody className="space-y-5">
          {loading ? (
            <LoadingBlock label="Checking Google connection status…" />
          ) : isConnected ? (
            <div className="space-y-4">
              <Alert tone="success" title="Google Account Connected">
                Your Google Calendar and Meet integration is active. Virtual callback requests from WhatsApp will automatically create Google Meet calendar invitations.
                {status?.scope && (
                  <p className="mt-2 text-xs opacity-75 font-mono">Granted scopes: {status.scope}</p>
                )}
              </Alert>

              <div className="flex flex-wrap items-center gap-3 pt-2">
                <Button variant="secondary" size="sm" onClick={fetchStatus} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                  Refresh Status
                </Button>
                <Button variant="ghost" size="sm" onClick={handleConnectGoogle}>
                  Reconnect / Switch Account
                </Button>
              </div>
            </div>
          ) : (
            <div className="space-y-5">
              {isExpired && (
                <Alert tone="warning" title="Authorization Expired">
                  Your Google OAuth token has expired without a valid refresh token. Please reconnect your account.
                </Alert>
              )}

              <div className="rounded-xl border border-dashed border-surface-line bg-surface-overlay/50 p-8 text-center">
                <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-accent-500/10 text-accent-400 mb-3">
                  <Video className="h-6 w-6" />
                </div>
                <h3 className="text-sm font-semibold text-slate-100">Connect Google Calendar</h3>
                <p className="mx-auto mt-1.5 max-w-md text-xs leading-relaxed text-slate-400">
                  Allow the AI bot to access Google Calendar to schedule live consultation appointments and send Google Meet video links instantly over WhatsApp.
                </p>
                <div className="mt-5">
                  <Button
                    variant="primary"
                    size="md"
                    onClick={handleConnectGoogle}
                    loading={isConnecting}
                    icon={!isConnecting ? <ExternalLink className="h-4 w-4" /> : undefined}
                  >
                    {isConnecting ? 'Opening Google Sign-in…' : 'Connect Google Workspace Account'}
                  </Button>
                </div>
              </div>

              <div className="rounded-lg bg-surface-overlay/30 p-4 text-xs text-slate-400 space-y-1.5 border border-surface-line/50">
                <p className="font-medium text-slate-300 flex items-center gap-1.5">
                  <ShieldCheck className="h-4 w-4 text-accent-400" /> Security &amp; Permissions
                </p>
                <p>• Only calendar event creation permissions are requested (Google Calendar API).</p>
                <p>• Credentials and tokens are securely isolated per tenant in the encrypted database.</p>
                <p>• You can revoke access at any time through your Google Security Dashboard.</p>
              </div>
            </div>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

export default GoogleConnectPanel
