// Google Account Connect Panel for Chatbot2.
// Allows admins/tenants to connect Google OAuth account for Meet scheduling.

import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert } from '@/components/ui/feedback'
import { Video, RefreshCw, ExternalLink } from 'lucide-react'
import { cn } from '@/lib/cn'
import { useToast } from '@/components/ui/toast'

export interface GoogleConnectPanelProps {
  tenantId?: string
  className?: string
}

interface ConnectionStatus {
  connected: boolean
  has_refresh_token?: boolean
  token_expired?: boolean
  scope?: string
}

export function GoogleConnectPanel({ tenantId = '', className }: GoogleConnectPanelProps) {
  const toast = useToast()

  const [status, setStatus] = useState<ConnectionStatus | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isConnecting, setIsConnecting] = useState(false)

  const fetchStatus = async () => {
    if (!tenantId) return
    try {
      setIsLoading(true)
      const resp = await fetch(`/api/tenants/${tenantId}/google-connect/status`)
      if (resp.ok) {
        const data = await resp.json()
        setStatus(data)
      } else {
        setStatus({ connected: false })
      }
    } catch {
      setStatus({ connected: false })
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()
  }, [tenantId])

  const handleConnectGoogle = async () => {
    if (!tenantId) return
    try {
      setIsConnecting(true)
      const resp = await fetch(`/api/tenants/${tenantId}/google-connect/oauth-url`)
      if (resp.ok) {
        const data = await resp.json()
        if (data.url) {
          window.location.href = data.url
          return
        }
      }
      toast.push('Failed to get Google authorization URL. Check server logs.', 'error')
    } catch {
      toast.push('Failed to initiate Google connection.', 'error')
    } finally {
      setIsConnecting(false)
    }
  }

  const isConnected = status?.connected && !status?.token_expired
  const isExpired = status?.connected && status?.token_expired && !status?.has_refresh_token

  return (
    <div className={cn('space-y-6', className)}>
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Google Account</h2>
        <p className="text-sm text-slate-400">
          Connect your Google account to enable Google Meet scheduling for callback requests.
        </p>
      </div>

      <Card>
        <CardHeader
          title="Google Calendar & Meet"
          description="Schedule meetings directly from callback requests using Google Meet"
          icon={<Video className="h-5 w-5 text-accent-400" />}
          actions={
            !isLoading && (
              <Badge tone={isConnected ? 'success' : isExpired ? 'warning' : 'muted'}>
                {isConnected ? 'Connected' : isExpired ? 'Token Expired' : 'Not Connected'}
              </Badge>
            )
          }
        />

        <CardBody className="space-y-4">
          {isLoading ? (
            <p className="text-sm text-slate-400">Checking connection status…</p>
          ) : isConnected ? (
            <>
              <Alert tone="success" title="Google account connected">
                You can now schedule Google Meet meetings directly from callback requests.
                {status?.scope && <p className="mt-1 text-xs">Scopes: {status.scope}</p>}
              </Alert>

              <div className="flex gap-2">
                <Button variant="ghost" size="sm" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={fetchStatus}>
                  Refresh Status
                </Button>
                <Button variant="ghost" size="sm" onClick={handleConnectGoogle}>
                  Reconnect / Switch Account
                </Button>
              </div>
            </>
          ) : (
            <>
              {isExpired && (
                <Alert tone="danger" title="Token expired">
                  Your Google token has expired and there is no refresh token stored. Please reconnect your account.
                </Alert>
              )}

              <div className="rounded-lg border border-dashed border-surface-line p-6 text-center space-y-3">
                <Video className="mx-auto h-10 w-10 text-slate-400" />
                <div>
                  <p className="font-medium text-slate-200">No Google account connected</p>
                  <p className="text-sm text-slate-400 mt-1">
                    Connect your Google account to start scheduling meetings with Google Meet.
                  </p>
                </div>
                <Button
                  variant="primary"
                  onClick={handleConnectGoogle}
                  loading={isConnecting}
                  icon={<ExternalLink className="h-4 w-4" />}
                >
                  Connect Google Account
                </Button>
              </div>

              <div className="text-xs text-slate-400 space-y-1">
                <p>• We request access to Google Calendar to create events and Meet links</p>
                <p>• Each admin/tenant has their own independent Google connection</p>
                <p>• You can revoke access at any time from your Google account settings</p>
              </div>
            </>
          )}
        </CardBody>
      </Card>
    </div>
  )
}

export default GoogleConnectPanel
