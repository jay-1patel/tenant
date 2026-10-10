// Callback Detail Panel for Chatbot2.
// Provides detailed view of a single callback request.

import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import {
  Calendar, Clock, User, Video, Phone, Mail, Edit, Trash2, CheckCircle, XCircle, 
  RefreshCw, Eye, ArrowLeft, MessageSquare, Copy, ExternalLink
} from 'lucide-react'
import { cn, useToast } from '@/lib/hooks'

import {
  useCallback as useCallbackHook,
  useCallbackStats,
  useTimeSlots,
  type CallbackRequest,
  getStatusColor,
  getStatusLabel,
  getPriorityColor,
  getTypeLabel,
  getStatusLabel as getLabelFromStatus,
  parseISODate,
  formatTime
} from '@/lib/callbacks'

import { format } from 'date-fns'

// Mock conversation history for demo
const MOCK_CONVERSATION = [
  { id: 1, sender: 'customer', message: 'Hi, I need help with product integration', timestamp: '2024-01-15T10:30:00' },
  { id: 2, sender: 'bot', message: 'Sure! What specific help do you need?', timestamp: '2024-01-15T10:32:00' },
  { id: 3, sender: 'customer', message: 'I want to schedule a callback with your technical team', timestamp: '2024-01-15T10:35:00' },
  { id: 4, sender: 'bot', message: 'I can connect you with our technical team. What time works best for you?', timestamp: '2024-01-15T10:36:00' },
]

export interface CallbackDetailPanelProps {
  className?: string
}

export function CallbackDetailPanel({ className }: CallbackDetailPanelProps) {
  const { tenantId, callbackId } = useParams() as { tenantId: string; callbackId: string }
  const navigate = useNavigate()
  const { toast } = useToast()
  
  const [callback, setCallback] = useState<CallbackRequest | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [editingNotes, setEditingNotes] = useState('')
  const [isEditDialogOpen, setIsEditDialogOpen] = useState(false)
  const [activeTab, setActiveTab] = useState('overview')
  // Schedule Meeting state
  const [isScheduleDialogOpen, setIsScheduleDialogOpen] = useState(false)
  const [scheduleStart, setScheduleStart] = useState('')
  const [scheduleEnd, setScheduleEnd] = useState('')
  const [isScheduling, setIsScheduling] = useState(false)
  
  // Fetch callback details
  useEffect(() => {
    if (!tenantId || !callbackId) return
    
    const fetchCallbackDetails = async () => {
      try {
        setIsLoading(true)
        setError(null)
        
        const response = await fetch(`/api/tenants/${tenantId}/callbacks/${callbackId}`)
        
        if (!response.ok) {
          throw new Error(`Failed to fetch callback: ${response.statusText}`)
        }
        
        const data = await response.json()
        setCallback(data.callback)
        setEditingNotes(data.callback.additional_info || '')
        
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load callback details')
        toast({ 
          title: 'Error', 
          description: error as string, 
          variant: 'destructive' 
        })
      } finally {
        setIsLoading(false)
      }
    }
    
    fetchCallbackDetails()
  }, [tenantId, callbackId, toast])
  
  const handleUpdateNotes = useCallbackHook(async () => {
    if (!callback) return
    
    try {
      const response = await fetch(`/api/tenants/${tenantId}/callbacks/${callbackId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ additional_info: editingNotes })
      })
      
      if (!response.ok) {
        throw new Error(`Failed to update callback: ${response.statusText}`)
      }
      
      toast({ title: 'Success', description: 'Additional notes updated successfully' })
      setIsEditDialogOpen(false)
      setCallback({ ...callback, additional_info: editingNotes })
      
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to update notes',
        variant: 'destructive' 
      })
    }
  }, [callback, tenantId, callbackId, editingNotes, toast])
  
  const handleCopyMeetLink = useCallbackHook(() => {
    if (!callback?.meet_link) return
    
    navigator.clipboard.writeText(callback.meet_link)
    toast({ title: 'Success', description: 'Meet link copied to clipboard' })
  }, [callback, toast])
  
  const openInCalendar = useCallbackHook(() => {
    if (!callback?.calendar_event_id) return
    
    // This would open Google Calendar with the event
    const calendarUrl = `https://calendar.google.com/calendar?action=VIEW&eid=${callback.calendar_event_id}`
    window.open(calendarUrl, '_blank')
  }, [callback])

  // Share meet link via WhatsApp
  const handleShareWhatsApp = useCallbackHook(() => {
    if (!callback?.meet_link || !callback?.wa_id) return
    const message = encodeURIComponent(`Join our meeting: ${callback.meet_link}`)
    const url = `https://wa.me/${callback.wa_id}?text=${message}`
    window.open(url, '_blank')
  }, [callback])

  // Schedule a Google Meet meeting
  const handleScheduleMeeting = useCallbackHook(async () => {
    if (!callback || !scheduleStart || !scheduleEnd) return
    try {
      setIsScheduling(true)
      const response = await fetch(
        `/api/tenants/${tenantId}/callbacks/${callbackId}/schedule`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            start_time: scheduleStart,
            end_time: scheduleEnd,
            timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
            summary: `Callback with ${callback.customer_name}`,
            attendee_email: callback.customer_email ?? ''
          })
        }
      )
      if (!response.ok) throw new Error(await response.text())
      const data = await response.json()
      setCallback({ ...callback, meet_link: data.meet_link, calendar_event_id: data.calendar_event_id })
      setIsScheduleDialogOpen(false)
      toast({ title: 'Meeting Scheduled!', description: `Google Meet link: ${data.meet_link}` })
    } catch (err) {
      toast({ title: 'Error', description: err instanceof Error ? err.message : 'Failed to schedule meeting', variant: 'destructive' })
    } finally {
      setIsScheduling(false)
    }
  }, [callback, tenantId, callbackId, scheduleStart, scheduleEnd, toast])
  
  if (isLoading) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="flex items-center space-x-4">
          <Button variant="outline" onClick={() => navigate('../callbacks')}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to List
          </Button>
        </div>
        <div className="text-center py-8">
          <p>Loading callback details...</p>
        </div>
      </div>
    )
  }
  
  if (error || !callback) {
    return (
      <div className={cn('space-y-6', className)}>
        <div className="flex items-center space-x-4">
          <Button variant="outline" onClick={() => navigate('../callbacks')}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to List
          </Button>
        </div>
        <Alert variant="destructive">
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>
            {error || 'Failed to load callback details'}
          </AlertDescription>
        </Alert>
      </div>
    )
  }
  
  const { date: formattedStartDate, time: formattedStartTime } = parseISODate(callback.scheduled_start_time || '')
  const { date: formattedEndDate, time: formattedEndTime } = parseISODate(callback.scheduled_end_time || '')
  const { date: formattedPreferredDate } = parseISODate(callback.preferred_date || '')
  const preferredTime = callback.preferred_time ? formatTime(callback.preferred_time) : null
  
  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between space-x-2">
        <div className="flex items-center space-x-4">
          <Button variant="outline" onClick={() => navigate('../callbacks')}>
            <ArrowLeft className="mr-2 h-4 w-4" />
            Back to List
          </Button>
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Callback Details</h2>
            <p className="text-muted-foreground">
              {callback.id}
            </p>
          </div>
        </div>
        
        <div className="flex items-center space-x-2">
          <Badge className={cn(getStatusColor(callback.status))}>
            {getLabelFromStatus(callback.status)}
          </Badge>
          {!callback.meet_link && (
            <Button size="sm" onClick={() => setIsScheduleDialogOpen(true)}>
              <Video className="mr-2 h-3 w-3" />
              Schedule Meeting
            </Button>
          )}
          {callback.meet_link && (
            <Button variant="outline" size="sm" onClick={handleCopyMeetLink}>
              <Copy className="mr-2 h-3 w-3" />
              Copy Meet Link
            </Button>
          )}
          {callback.meet_link && callback.wa_id && (
            <Button variant="outline" size="sm" onClick={handleShareWhatsApp}>
              <MessageSquare className="mr-2 h-3 w-3" />
              Share via WhatsApp
            </Button>
          )}
          {callback.calendar_event_id && (
            <Button variant="outline" size="sm" onClick={openInCalendar}>
              <ExternalLink className="mr-2 h-3 w-3" />
              Open in Calendar
            </Button>
          )}
        </div>
      </div>

      {/* Status and Actions */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader>
            <CardTitle>Customer Information</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center space-x-3">
              <User className="h-5 w-5 text-muted-foreground" />
              <div className="space-y-1">
                <p className="font-medium">{callback.customer_name}</p>
                <p className="text-sm text-muted-foreground">
                  Customer Name
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <Phone className="h-5 w-5 text-muted-foreground" />
              <div className="space-y-1">
                <p className="font-medium">{callback.wa_id}</p>
                <p className="text-sm text-muted-foreground">
                  WhatsApp ID
                </p>
              </div>
            </div>
            
            {callback.customer_phone && (
              <div className="flex items-center space-x-3">
                <Phone className="h-5 w-5 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="font-medium">{callback.customer_phone}</p>
                  <p className="text-sm text-muted-foreground">
                    Phone
                  </p>
                </div>
              </div>
            )}
            
            {callback.customer_email && (
              <div className="flex items-center space-x-3">
                <Mail className="h-5 w-5 text-muted-foreground" />
                <div className="space-y-1">
                  <p className="font-medium">{callback.customer_email}</p>
                  <p className="text-sm text-muted-foreground">
                    Email
                  </p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Callback Details</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-primary/10">
                <Calendar className="h-5 w-5 text-primary" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">{getTypeLabel(callback.callback_type)}</p>
                <p className="text-sm text-muted-foreground">
                  Callback Type
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-primary/10">
                <Edit className="h-5 w-5 text-primary" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">{callback.purpose || 'No specific purpose'}</p>
                <p className="text-sm text-muted-foreground">
                  Purpose
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <Badge variant="outline" className={cn(getPriorityColor(callback.priority))}>
                {callback.priority.toUpperCase()}
              </Badge>
              <div className="space-y-1">
                <p className="text-sm text-muted-foreground">
                  Priority Level
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-full bg-primary/10">
                <MessageSquare className="h-5 w-5 text-primary" />
              </div>
              <div className="space-y-1">
                <p className="font-medium">{callback.additional_info || 'No additional notes'}</p>
                <p className="text-sm text-muted-foreground">
                  Additional Information
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Scheduling</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center space-x-3">
              <Clock className="h-5 w-5 text-muted-foreground" />
              <div className="space-y-1">
                {callback.scheduled_start_time ? (
                  <>
                    <p className="font-medium">{formattedStartDate}</p>
                    <p className="text-sm text-muted-foreground">{formattedStartTime} to {formattedEndTime}</p>
                    <p className="text-xs text-muted-foreground">{callback.timezone}</p>
                  </>
                ) : (
                  <>
                    <p className="font-medium">{formattedPreferredDate !== 'N/A' ? formattedPreferredDate : 'Not scheduled'}</p>
                    {preferredTime && <p className="text-sm text-muted-foreground">{preferredTime}</p>}
                  </>
                )}
                <p className="text-sm text-muted-foreground">
                  {callback.scheduled_start_time ? 'Scheduled Time' : 'Preferred Time'}
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <User className="h-5 w-5 text-muted-foreground" />
              <div className="space-y-1">
                <p className="font-medium">{callback.assigned_agent_name || 'Not assigned'}</p>
                {callback.assigned_agent_id && (
                  <p className="text-xs text-muted-foreground">{callback.assigned_agent_id}</p>
                )}
                <p className="text-sm text-muted-foreground">
                  {callback.assigned_agent_name ? 'Assigned Agent' : 'Agent'}
                </p>
              </div>
            </div>
            
            <div className="flex items-center space-x-3">
              <Video className="h-5 w-5 text-muted-foreground" />
              <div className="space-y-1">
                {callback.meet_link ? (
                  <a 
                    href={callback.meet_link} 
                    target="_blank" 
                    className="font-medium text-primary underline hover:no-underline"
                  >
                    Join Google Meet
                  </a>
                ) : (
                  <p className="font-medium text-muted-foreground">Not created</p>
                )}
                <p className="text-xs text-muted-foreground">{callback.calendar_event_id ? 'Meet link created' : 'No meet link'}</p>
                <p className="text-sm text-muted-foreground">
                  Google Meet Link
                </p>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Time Slots Preview (if available) */}
      {callback.preferred_date && !callback.scheduled_start_time && (
        <Card>
          <CardHeader>
            <CardTitle>Suggested Time Slots for {callback.preferred_date}</CardTitle>
            <CardDescription>
              Available slots for scheduling this callback
            </CardDescription>
          </CardHeader>
          <CardContent>
            <p className="text-sm text-muted-foreground">
              Use the schedule action to set up a meeting with Google Meet
            </p>
          </CardContent>
        </Card>
      )}

      {/* Conversation History */}
      <Card>
        <CardHeader>
          <CardTitle>Conversation History</CardTitle>
          <CardDescription>
            Messages leading to this callback request
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="overview" onValueChange={setActiveTab} className="w-full">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="conversation">Messages</TabsTrigger>
              <TabsTrigger value="notes">Additional Notes</TabsTrigger>
            </TabsList>
            
            <TabsContent value="overview" className="py-4">
              <div className="space-y-4">
                <div className="flex items-center justify-between py-2 border-b">
                  <span className="text-muted-foreground">Callback ID</span>
                  <span className="font-mono">{callback.id}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b">
                  <span className="text-muted-foreground">Created</span>
                  <span>{new Date(callback.created_at).toLocaleString()}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b">
                  <span className="text-muted-foreground">Last Updated</span>
                  <span>{new Date(callback.updated_at).toLocaleString()}</span>
                </div>
                <div className="flex items-center justify-between py-2 border-b">
                  <span className="text-muted-foreground">Status</span>
                  <Badge className={cn(getStatusColor(callback.status))}>
                    {getLabelFromStatus(callback.status)}
                  </Badge>
                </div>
                <div className="flex items-center justify-between py-2 border-b">
                  <span className="text-muted-foreground">Tenant ID</span>
                  <span className="font-mono">{callback.tenant_id}</span>
                </div>
                
                {Object.keys(callback.metadata || {}).length > 0 && (
                  <div className="pt-4">
                    <h4 className="font-medium mb-2">Metadata</h4>
                    <pre className="text-sm bg-muted p-3 rounded overflow-x-auto">
                      {JSON.stringify(callback.metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            </TabsContent>
            
            <TabsContent value="conversation" className="py-4">
              {MOCK_CONVERSATION.map((msg, index) => (
                <div
                  key={msg.id}
                  className={cn(
                    'flex space-x-3 pb-4',
                    index < MOCK_CONVERSATION.length - 1 ? 'border-b' : ''
                  )}
                >
                  <div className={cn(
                    'flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center text-white text-sm',
                    msg.sender === 'customer' ? 'bg-blue-500' : 'bg-gray-500'
                  )}>
                    {msg.sender === 'customer' ? 'C' : 'B'}
                  </div>
                  <div className="flex-1">
                    <div className="flex items-center space-x-2 mb-1">
                      <span className="font-medium text-sm">
                        {msg.sender === 'customer' ? 'Customer' : 'Bot'}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {new Date(msg.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="text-sm bg-muted/50 p-3 rounded-lg">
                      {msg.message}
                    </p>
                  </div>
                </div>
              ))}
            </TabsContent>
            
            <TabsContent value="notes" className="py-4">
              <div className="space-y-4">
                {callback.additional_info ? (
                  <div className="bg-muted/50 p-4 rounded-lg">
                    <p className="whitespace-pre-wrap">{callback.additional_info}</p>
                  </div>
                ) : (
                  <p className="text-muted-foreground text-center py-4">
                    No additional notes
                  </p>
                )}
                
                <div className="pt-4">
                  <Button variant="outline" onClick={() => {
                    setEditingNotes(callback.additional_info || '')
                    setIsEditDialogOpen(true)
                  }}>
                    <Edit className="mr-2 h-4 w-4" />
                    Edit Notes
                  </Button>
                </div>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {/* Edit Notes Dialog */}
      <Dialog open={isEditDialogOpen} onOpenChange={setIsEditDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Edit Additional Notes</DialogTitle>
            <DialogDescription>
              Update the additional information for this callback request
            </DialogDescription>
          </DialogHeader>
          
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label htmlFor="notes" className="text-sm font-medium">
                Notes
              </label>
              <Input
                id="notes"
                value={editingNotes}
                onChange={(e) => setEditingNotes(e.target.value)}
                placeholder="Enter additional notes or information about this callback"
                className="min-h-[100px]"
              />
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setIsEditDialogOpen(false)
              setEditingNotes(callback?.additional_info || '')
            }}>
              Cancel
            </Button>
            <Button onClick={handleUpdateNotes}>
              Save Changes
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Schedule Meeting Dialog */}
      <Dialog open={isScheduleDialogOpen} onOpenChange={setIsScheduleDialogOpen}>
        <DialogContent className="sm:max-w-[480px]">
          <DialogHeader>
            <DialogTitle>Schedule a Google Meet</DialogTitle>
            <DialogDescription>
              Pick a start and end time. A Google Calendar event with a Meet link will be created.
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <label htmlFor="schedule-start" className="text-sm font-medium">
                Start Time
              </label>
              <input
                id="schedule-start"
                type="datetime-local"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={scheduleStart}
                onChange={(e) => setScheduleStart(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="schedule-end" className="text-sm font-medium">
                End Time
              </label>
              <input
                id="schedule-end"
                type="datetime-local"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={scheduleEnd}
                onChange={(e) => setScheduleEnd(e.target.value)}
              />
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={() => setIsScheduleDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleScheduleMeeting} disabled={isScheduling || !scheduleStart || !scheduleEnd}>
              {isScheduling ? 'Scheduling...' : 'Schedule Meeting'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default CallbackDetailPanel