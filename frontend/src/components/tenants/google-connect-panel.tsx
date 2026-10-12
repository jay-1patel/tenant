// Google Account Connect Panel for Chatbot2.
// Allows admins/tenants to connect Google OAuth account for Meet scheduling.

import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { CheckCircle, XCircle, Video, RefreshCw, ExternalLink } from 'lucide-react'
import { cn, useToast } from '@/lib/hooks'

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

export function GoogleConnectPanel({ tenantId: propTenantId, className }: GoogleConnectPanelProps) {
  const params = useParams() as { tenantId?: string }
  const tenantId = propTenantId || params.tenantId || ''
  const { toast } = useToast()

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
      }
    } catch (err) {
      console.error('Failed to fetch Google connection status:', err)
    } finally {
      setIsLoading(false)
    }
  }

  useEffect(() => {
    fetchStatus()

    // Check URL for success/error from OAuth callback redirect
    const urlParams = new URLSearchParams(window.location.search)
    if (urlParams.get('success') === 'true') {
      toast({ title: 'Google Connected!', description: 'Your Google account has been connected successfully.' })
      // Clean URL
      window.history.replaceState({}, '', window.location.pathname)
      fetchStatus()
    } else if (urlParams.get('error')) {
      toast({
        title: 'Connection Failed',
        description: `OAuth error: ${urlParams.get('error')}`,
        variant: 'destructive',
      })
      window.history.replaceState({}, '', window.location.pathname)
    }
  }, [tenantId])

  const handleConnectGoogle = async () => {
    if (!tenantId) return
    try {
      setIsConnecting(true)
      const resp = await fetch(`/api/tenants/${tenantId}/google-connect/oauth-url`)
      if (!resp.ok) {
        const err = await resp.json()
        throw new Error(err.detail || 'Failed to get OAuth URL')
      }
      const { oauth_url } = await resp.json()
      // Redirect to Google consent screen
      window.location.href = oauth_url
    } catch (err) {
      toast({
        title: 'Error',
        description: err instanceof Error ? err.message : 'Failed to start OAuth flow',
        variant: 'destructive',
      })
      setIsConnecting(false)
    }
  }

  const isConnected = status?.connected && !status?.token_expired
  const isExpired = status?.connected && status?.token_expired && !status?.has_refresh_token

  return (
    <div className={cn('space-y-6', className)}>
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Google Account</h2>
        <p className="text-muted-foreground">
          Connect your Google account to enable Google Meet scheduling for callback requests.
        </p>
      </div>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center space-x-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-50">
                <Video className="h-5 w-5 text-blue-600" />
              </div>
              <div>
                <CardTitle>Google Calendar & Meet</CardTitle>
                <CardDescription>
                  Schedule meetings directly from callback requests using Google Meet
                </CardDescription>
              </div>
            </div>
            {!isLoading && (
              <Badge
                className={cn(
                  isConnected
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : isExpired
                    ? 'bg-yellow-100 text-yellow-800 border-yellow-200'
                    : 'bg-gray-100 text-gray-700 border-gray-200'
                )}
              >
                {isConnected ? 'Connected' : isExpired ? 'Token Expired' : 'Not Connected'}
              </Badge>
            )}
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {isLoading ? (
            <p className="text-sm text-muted-foreground">Checking connection status…</p>
          ) : isConnected ? (
            <>
              <Alert className="border-green-200 bg-green-50">
                <CheckCircle className="h-4 w-4 text-green-600" />
                <AlertTitle className="text-green-800">Google account connected</AlertTitle>
                <AlertDescription className="text-green-700">
                  You can now schedule Google Meet meetings directly from callback requests.
                  {status?.scope && (
                    <p className="mt-1 text-xs">Scopes: {status.scope}</p>
                  )}
                </AlertDescription>
              </Alert>

              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={fetchStatus}>
                  <RefreshCw className="mr-2 h-3 w-3" />
                  Refresh Status
                </Button>
                <Button variant="outline" size="sm" onClick={handleConnectGoogle}>
                  Reconnect / Switch Account
                </Button>
              </div>
            </>
          ) : (
            <>
              {isExpired && (
                <Alert variant="destructive" className="mb-2">
                  <XCircle className="h-4 w-4" />
                  <AlertTitle>Token expired</AlertTitle>
                  <AlertDescription>
                    Your Google token has expired and there is no refresh token stored. Please reconnect your account.
                  </AlertDescription>
                </Alert>
              )}

              <div className="rounded-lg border border-dashed p-6 text-center space-y-3">
                <Video className="mx-auto h-10 w-10 text-muted-foreground" />
                <div>
                  <p className="font-medium">No Google account connected</p>
                  <p className="text-sm text-muted-foreground mt-1">
                    Connect your Google account to start scheduling meetings with Google Meet.
                  </p>
                </div>
                <Button onClick={handleConnectGoogle} disabled={isConnecting} className="mt-2">
                  {isConnecting ? 'Redirecting to Google…' : 'Connect Google Account'}
                  {!isConnecting && <ExternalLink className="ml-2 h-3 w-3" />}
                </Button>
              </div>

              <div className="text-xs text-muted-foreground space-y-1">
                <p>• We request access to Google Calendar to create events and Meet links</p>
                <p>• Each admin/tenant has their own independent Google connection</p>
                <p>• You can revoke access at any time from your Google account settings</p>
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

export default GoogleConnectPanel
