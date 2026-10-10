// Callback Booking Management Panel for Chatbot2.

import { useState, useEffect, useCallback } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Calendar, Clock, User, Video, Phone, Mail, Edit, Trash2, CheckCircle, XCircle, RefreshCw, Eye, Plus, Filter, Search, MoreVertical } from 'lucide-react'
import { cn, useToast } from '@/lib/hooks'

import {
  useCallbacks,
  useCallbackStats,
  useUpcomingCallbacks,
  useCreateCallback,
  useUpdateCallback,
  useScheduleCallback,
  useCancelCallback,
  useCompleteCallback,
  useRescheduleCallback,
  useTimeSlots,
  type CallbackRequest,
  type CreateCallbackRequest,
  type ScheduleCallbackRequest,
  type TimeSlot,
  type CancelCallbackRequest,
  type CompleteCallbackRequest,
  type RescheduleCallbackRequest,
  CALLBACK_TYPES,
  CALLBACK_STATUSES,
  CALLBACK_PRIORITIES,
  getStatusColor,
  getStatusLabel,
  getPriorityColor,
  getTypeLabel,
  canScheduleCallback,
  canCancelCallback,
  canRescheduleCallback,
  canCompleteCallback,
  formatDateTimeForDisplay,
  parseISODate
} from '@/lib/callbacks'

import { useTenants } from '@/lib/tenants'
import { format } from 'date-fns'

export interface CallbacksPanelProps {
  className?: string
}

// Mock agents for demo purposes - in production these would come from API
const MOCK_AGENTS = [
  { id: 'agent_001', name: 'John Smith', email: 'john@company.com', phone: '+919999999999' },
  { id: 'agent_002', name: 'Sarah Johnson', email: 'sarah@company.com', phone: '+919999999998' },
  { id: 'agent_003', name: 'Mike Davis', email: 'mike@company.com', phone: '+919999999997' },
]

export function CallbacksPanel({ className }: CallbacksPanelProps) {
  const { tenantId } = useParams() as { tenantId: string }
  const navigate = useNavigate()
  const { toast } = useToast()
  
  const [searchTerm, setSearchTerm] = useState('')
  const [filterStatus, setFilterStatus] = useState<string>('')
  const [filterType, setFilterType] = useState<string>('')
  const [isCreateDialogOpen, setIsCreateDialogOpen] = useState(false)
  const [isScheduleDialogOpen, setIsScheduleDialogOpen] = useState(false)
  const [isCancelDialogOpen, setIsCancelDialogOpen] = useState(false)
  const [isCompleteDialogOpen, setIsCompleteDialogOpen] = useState(false)
  const [isRescheduleDialogOpen, setIsRescheduleDialogOpen] = useState(false)
  const [selectedCallback, setSelectedCallback] = useState<CallbackRequest | null>(null)
  const [selectedDate, setSelectedDate] = useState<string>(format(new Date(), 'yyyy-MM-dd'))
  const [selectedTimeSlot, setSelectedTimeSlot] = useState<TimeSlot | null>(null)
  const [selectedAgent, setSelectedAgent] = useState<{id: string; name: string} | null>(null)
  
  // Form states
  const [formData, setFormData] = useState<CreateCallbackRequest>({
    customer_name: '',
    wa_id: '',
    callback_type: 'general',
    purpose: '',
    priority: 'medium',
    customer_email: '',
    customer_phone: '',
    preferred_date: '',
    preferred_time: '',
    additional_info: ''
  })
  
  const [cancelReason, setCancelReason] = useState('')
  const [completionNotes, setCompletionNotes] = useState('')
  const [completionOutcome, setCompletionOutcome] = useState('success')
  const [rescheduleData, setRescheduleData] = useState({
    new_date: selectedDate,
    new_start_time: '',
    new_end_time: '',
    reason: ''
  })
  
  // API hooks
  const { data: callbacksData, isLoading, refetch } = useCallbacks(tenantId, {
    status: filterStatus || undefined,
    limit: 50
  })
  
  const { data: statsData } = useCallbackStats(tenantId)
  const { data: upcomingCallbacksData } = useUpcomingCallbacks(tenantId)
  const { data: timeSlotsData } = useTimeSlots(tenantId, selectedDate, undefined, 30)
  
  const createMutation = useCreateCallback()
  const updateMutation = useUpdateCallback()
  const scheduleMutation = useScheduleCallback()
  const cancelMutation = useCancelCallback()
  const completeMutation = useCompleteCallback()
  const rescheduleMutation = useRescheduleCallback()
  
  // Handlers
  const handleCreateCallback = useCallback(async () => {
    if (!tenantId) return
    
    try {
      await createMutation.mutateAsync({
        tenantId,
        data: formData
      })
      
      toast({ title: 'Success', description: 'Callback request created successfully' })
      setIsCreateDialogOpen(false)
      setFormData({
        customer_name: '',
        wa_id: '',
        callback_type: 'general',
        purpose: '',
        priority: 'medium',
        customer_email: '',
        customer_phone: '',
        preferred_date: '',
        preferred_time: '',
        additional_info: ''
      })
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to create callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, formData, createMutation, refetch, toast])
  
  const handleUpdateCallback = useCallback(async (callback: CallbackRequest, updates: Partial<CallbackRequest>) => {
    if (!tenantId) return
    
    try {
      await updateMutation.mutateAsync({
        tenantId,
        callbackId: callback.id,
        data: updates
      })
      toast({ title: 'Success', description: 'Callback updated successfully' })
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to update callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, updateMutation, refetch, toast])
  
  const handleScheduleCallback = useCallback(async () => {
    if (!tenantId || !selectedCallback || !selectedAgent || !selectedTimeSlot) return
    
    try {
      const startTime = `${selectedDate}T${selectedTimeSlot.start_time}:00`
      const endTime = `${selectedDate}T${selectedTimeSlot.end_time}:00`
      
      await scheduleMutation.mutateAsync({
        tenantId,
        callbackId: selectedCallback.id,
        data: {
          agent_id: selectedAgent.id,
          agent_name: selectedAgent.name,
          start_time: startTime,
          end_time: endTime,
          send_notifications: true
        }
      })
      
      toast({ title: 'Success', description: 'Callback scheduled successfully with Google Meet' })
      setIsScheduleDialogOpen(false)
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to schedule callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, selectedCallback, selectedAgent, selectedTimeSlot, selectedDate, scheduleMutation, refetch, toast])
  
  const handleCancelCallback = useCallback(async () => {
    if (!tenantId || !selectedCallback) return
    
    try {
      await cancelMutation.mutateAsync({
        tenantId,
        callbackId: selectedCallback.id,
        data: {
          reason: cancelReason,
          notify_customer: true,
          notify_agent: true
        }
      })
      
      toast({ title: 'Success', description: 'Callback cancelled successfully' })
      setIsCancelDialogOpen(false)
      setCancelReason('')
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to cancel callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, selectedCallback, cancelReason, cancelMutation, refetch, toast])
  
  const handleCompleteCallback = useCallback(async () => {
    if (!tenantId || !selectedCallback) return
    
    try {
      await completeMutation.mutateAsync({
        tenantId,
        callbackId: selectedCallback.id,
        data: {
          meeting_notes: completionNotes,
          outcome: completionOutcome,
          follow_up_required: false,
          follow_up_notes: ''
        }
      })
      
      toast({ title: 'Success', description: 'Callback marked as completed' })
      setIsCompleteDialogOpen(false)
      setCompletionNotes('')
      setCompletionOutcome('success')
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to complete callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, selectedCallback, completionNotes, completionOutcome, completeMutation, refetch, toast])
  
  const handleRescheduleCallback = useCallback(async () => {
    if (!tenantId || !selectedCallback) return
    
    try {
      const startTime = `${rescheduleData.new_date}T${rescheduleData.new_start_time}:00`
      const endTime = `${rescheduleData.new_date}T${rescheduleData.new_end_time}:00`
      
      await rescheduleMutation.mutateAsync({
        tenantId,
        callbackId: selectedCallback.id,
        data: {
          new_start_time: startTime,
          new_end_time: endTime,
          reason: rescheduleData.reason,
          notify_participants: true
        }
      })
      
      toast({ title: 'Success', description: 'Callback rescheduled successfully' })
      setIsRescheduleDialogOpen(false)
      setRescheduleData({
        new_date: format(new Date(), 'yyyy-MM-dd'),
        new_start_time: '',
        new_end_time: '',
        reason: ''
      })
      refetch()
    } catch (error) {
      toast({ 
        title: 'Error', 
        description: error instanceof Error ? error.message : 'Failed to reschedule callback',
        variant: 'destructive' 
      })
    }
  }, [tenantId, selectedCallback, rescheduleData, rescheduleMutation, refetch, toast])
  
  const openScheduleDialog = useCallback((callback: CallbackRequest) => {
    setSelectedCallback(callback)
    setSelectedAgent(null)
    setSelectedTimeSlot(null)
    setIsScheduleDialogOpen(true)
  }, [])
  
  const openCancelDialog = useCallback((callback: CallbackRequest) => {
    setSelectedCallback(callback)
    setCancelReason('')
    setIsCancelDialogOpen(true)
  }, [])
  
  const openCompleteDialog = useCallback((callback: CallbackRequest) => {
    setSelectedCallback(callback)
    setCompletionNotes('')
    setCompletionOutcome('success')
    setIsCompleteDialogOpen(true)
  }, [])
  
  const openRescheduleDialog = useCallback((callback: CallbackRequest) => {
    setSelectedCallback(callback)
    setRescheduleData({
      new_date: callback.preferred_date || format(new Date(), 'yyyy-MM-dd'),
      new_start_time: '',
      new_end_time: '',
      reason: ''
    })
    setIsRescheduleDialogOpen(true)
  }, [])
  
  // Filter callbacks based on search term and filters
  const filteredCallbacks = callbacksData?.callbacks?.filter(callback => {
    const matchesSearch = searchTerm.toLowerCase() === '' || 
      callback.customer_name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      callback.wa_id.includes(searchTerm) ||
      callback.id.includes(searchTerm) ||
      callback.callback_type.toLowerCase().includes(searchTerm.toLowerCase())
    
    const matchesStatus = !filterStatus || callback.status === filterStatus
    const matchesType = !filterType || callback.callback_type === filterType
    
    return matchesSearch && matchesStatus && matchesType
  }) || []
  
  return (
    <div className={cn('space-y-6', className)}>
      {/* Header */}
      <div className="flex items-center justify-between space-x-2">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Callback Booking Pipeline</h2>
          <p className="text-muted-foreground">
            Manage customer callback requests, schedule meetings, and track conversions
          </p>
        </div>
        <Button onClick={() => setIsCreateDialogOpen(true)}>
          <Plus className="mr-2 h-4 w-4" />
          New Callback Request
        </Button>
      </div>

      {/* Stats Overview */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-x-2">
            <CardTitle className="text-sm font-medium">Total Callbacks</CardTitle>
            <Phone className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{statsData?.total_callbacks || 0}</div>
            <p className="text-xs text-muted-foreground">
              Last {statsData?.period?.days || 30} days
            </p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-x-2">
            <CardTitle className="text-sm font-medium">Scheduled Today</CardTitle>
            <Calendar className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{
              upcomingCallbacksData?.upcoming_callbacks?.filter(cb => 
                cb.status === 'scheduled' && 
                new Date(cb.scheduled_start_time || '').toDateString() === new Date().toDateString()
              ).length || 0
            }</div>
            <p className="text-xs text-muted-foreground">
              Upcoming meetings
            </p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-x-2">
            <CardTitle className="text-sm font-medium">Completion Rate</CardTitle>
            <CheckCircle className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-green-600">
              {statsData?.completion_rate?.toFixed(1) || '0'}%
            </div>
            <p className="text-xs text-muted-foreground">
              Successful callbacks
            </p>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-x-2">
            <CardTitle className="text-sm font-medium">Pending Actions</CardTitle>
            <Clock className="h-4 w-4 text-muted-foreground" />
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold text-orange-600">
              {filteredCallbacks.filter(cb => cb.status === 'pending').length}
            </div>
            <p className="text-xs text-muted-foreground">
              Awaiting confirmation
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Filters and Search */}
      <Card>
        <CardHeader>
          <CardTitle>Filter Callbacks</CardTitle>
          <CardDescription>
            Find callbacks by status, type, or search term
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="grid gap-4 md:grid-cols-4">
            <div className="space-y-2">
              <label className="text-sm font-medium">Search</label>
              <div className="relative">
                <Search className="absolute left-2 top-2.5 h-4 w-4 text-muted-foreground" />
                <Input
                  placeholder="Customer name, WhatsApp ID..."
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Status</label>
              <Select value={filterStatus} onValueChange={setFilterStatus}>
                <SelectTrigger>
                  <SelectValue placeholder="All Statuses" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All Statuses</SelectItem>
                  {CALLBACK_STATUSES.map(status => (
                    <SelectItem key={status} value={status}>
                      <span className={cn("flex items-center", getStatusColor(status))}>
                        {getStatusLabel(status)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">Type</label>
              <Select value={filterType} onValueChange={setFilterType}>
                <SelectTrigger>
                  <SelectValue placeholder="All Types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="">All Types</SelectItem>
                  {CALLBACK_TYPES.map(type => (
                    <SelectItem key={type} value={type}>
                      {getTypeLabel(type)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label className="text-sm font-medium">&nbsp;</label>
              <Button variant="outline" onClick={() => {
                setSearchTerm('')
                setFilterStatus('')
                setFilterType('')
              }}>
                <XCircle className="mr-2 h-4 w-4" />
                Clear Filters
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Callbacks Table */}
      <Card>
        <CardHeader>
          <CardTitle>Callback Requests</CardTitle>
          <CardDescription>
            {filteredCallbacks.length} callback requests found
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Customer</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Priority</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>Scheduled</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {isLoading ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-4">
                      Loading...
                    </TableCell>
                  </TableRow>
                ) : filteredCallbacks.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-4 text-muted-foreground">
                      No callbacks found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredCallbacks.map((callback) => {
                    const canSchedule = canScheduleCallback(callback)
                    const canCancel = canCancelCallback(callback)
                    const canReschedule = canRescheduleCallback(callback)
                    const canComplete = canCompleteCallback(callback)
                    const { date: formattedDate, time: formattedTime } = parseISODate(callback.scheduled_start_time || '')
                    
                    return (
                      <TableRow key={callback.id}>
                        <TableCell>
                          <div className="font-medium">{callback.customer_name}</div>
                          <div className="text-sm text-muted-foreground">
                            {callback.wa_id} {callback.customer_email && `| ${callback.customer_email}`}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={cn("capitalize", getStatusColor(callback.callback_type))}>
                            {getTypeLabel(callback.callback_type)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge className={cn(getStatusColor(callback.status))}>
                            {getStatusLabel(callback.status)}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          <Badge variant="outline" className={cn(getPriorityColor(callback.priority))}>
                            {callback.priority}
                          </Badge>
                        </TableCell>
                        <TableCell>
                          {callback.assigned_agent_name || '-'} {callback.assigned_agent_id && (
                            <div className="text-xs text-muted-foreground">{callback.assigned_agent_id}</div>
                          )}
                        </TableCell>
                        <TableCell>
                          {formattedDate !== 'N/A' && formattedTime !== 'N/A' ? (
                            <div>
                              <div>{formattedDate}</div>
                              <div className="text-sm text-muted-foreground">{formattedTime}</div>
                            </div>
                          ) : (
                            callback.preferred_date && callback.preferred_time ? (
                              <div>
                                <div>{callback.preferred_date}</div>
                                <div className="text-sm text-muted-foreground">{callback.preferred_time}</div>
                              </div>
                            ) : '-'
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex space-x-2">
                            {(canSchedule || canReschedule) && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openScheduleDialog(callback)}
                                disabled={!canSchedule && !canReschedule}
                              >
                                <Calendar className="h-3 w-3" />
                              </Button>
                            )}
                            {canComplete && callback.status !== 'completed' && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openCompleteDialog(callback)}
                              >
                                <CheckCircle className="h-3 w-3" />
                              </Button>
                            )}
                            {canCancel && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openCancelDialog(callback)}
                              >
                                <XCircle className="h-3 w-3" />
                              </Button>
                            )}
                            {canReschedule && (
                              <Button
                                variant="outline"
                                size="sm"
                                onClick={() => openRescheduleDialog(callback)}
                              >
                                <RefreshCw className="h-3 w-3" />
                              </Button>
                            )}
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => navigate(`./${callback.id}`)}
                            >
                              <Eye className="h-3 w-3" />
                            </Button>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Create Callback Dialog */}
      <Dialog open={isCreateDialogOpen} onOpenChange={setIsCreateDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Create New Callback Request</DialogTitle>
            <DialogDescription>
              Fill in the details to create a new callback request for a customer
            </DialogDescription>
          </DialogHeader>
          
          <div className="grid grid-cols-2 gap-4 py-4">
            <div className="space-y-2">
              <label htmlFor="customer_name" className="text-sm font-medium">
                Customer Name <span className="text-red-500">*</span>
              </label>
              <Input
                id="customer_name"
                value={formData.customer_name}
                onChange={(e) => setFormData({...formData, customer_name: e.target.value})}
                placeholder="Enter customer name"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="wa_id" className="text-sm font-medium">
                WhatsApp ID <span className="text-red-500">*</span>
              </label>
              <Input
                id="wa_id"
                value={formData.wa_id}
                onChange={(e) => setFormData({...formData, wa_id: e.target.value})}
                placeholder="919876543210"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="callback_type" className="text-sm font-medium">
                Callback Type
              </label>
              <Select
                value={formData.callback_type}
                onValueChange={(value) => setFormData({...formData, callback_type: value})}
              >
                <SelectTrigger id="callback_type">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CALLBACK_TYPES.map(type => (
                    <SelectItem key={type} value={type}>
                      {getTypeLabel(type)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label htmlFor="priority" className="text-sm font-medium">
                Priority
              </label>
              <Select
                value={formData.priority}
                onValueChange={(value) => setFormData({...formData, priority: value})}
              >
                <SelectTrigger id="priority">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {CALLBACK_PRIORITIES.map(priority => (
                    <SelectItem key={priority} value={priority} className={getPriorityColor(priority)}>
                      {priority.charAt(0).toUpperCase() + priority.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-2">
              <label htmlFor="customer_email" className="text-sm font-medium">
                Email
              </label>
              <Input
                id="customer_email"
                type="email"
                value={formData.customer_email || ''}
                onChange={(e) => setFormData({...formData, customer_email: e.target.value})}
                placeholder="customer@email.com"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="customer_phone" className="text-sm font-medium">
                Phone
              </label>
              <Input
                id="customer_phone"
                value={formData.customer_phone || ''}
                onChange={(e) => setFormData({...formData, customer_phone: e.target.value})}
                placeholder="+91 98765 43210"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="purpose" className="text-sm font-medium">
                Purpose
              </label>
              <Input
                id="purpose"
                value={formData.purpose}
                onChange={(e) => setFormData({...formData, purpose: e.target.value})}
                placeholder="Brief description of callback purpose"
              />
            </div>
            <div className="space-y-2">
              <label htmlFor="additional_info" className="text-sm font-medium">
                Additional Info
              </label>
              <Input
                id="additional_info"
                value={formData.additional_info}
                onChange={(e) => setFormData({...formData, additional_info: e.target.value})}
                placeholder="Any additional context"
              />
            </div>
          </div>
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCreateDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleCreateCallback} disabled={!formData.customer_name || !formData.wa_id}>
              Create Callback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Schedule Callback Dialog */}
      <Dialog open={isScheduleDialogOpen} onOpenChange={setIsScheduleDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Schedule Callback Meeting</DialogTitle>
            <DialogDescription>
              Schedule a Google Meet meeting for this callback request
            </DialogDescription>
          </DialogHeader>
          
          {selectedCallback && (
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <label className="text-sm font-medium">Customer</label>
                <div className="p-3 border rounded-lg bg-muted/50">
                  <div className="font-medium">{selectedCallback.customer_name}</div>
                  <div className="text-sm text-muted-foreground">
                    {selectedCallback.wa_id} | {selectedCallback.callback_type}
                  </div>
                  <div className="text-sm text-muted-foreground">
                    Preferred: {selectedCallback.preferred_date} {selectedCallback.preferred_time}
                  </div>
                </div>
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Select Date</label>
                <Input
                  type="date"
                  value={selectedDate}
                  onChange={(e) => setSelectedDate(e.target.value)}
                  min={format(new Date(), 'yyyy-MM-dd')}
                />
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Available Time Slots</label>
                <div className="max-h-[200px] overflow-y-auto border rounded-lg p-3 space-y-2">
                  {timeSlotsData?.time_slots?.length ? (
                    timeSlotsData.time_slots.map((slot) => (
                      <Button
                        key={slot.id}
                        variant={selectedTimeSlot?.id === slot.id ? 'default' : 'outline'}
                        size="sm"
                        className="w-full justify-start"
                        onClick={() => setSelectedTimeSlot(slot)}
                      >
                        {slot.display_text}
                      </Button>
                    ))
                  ) : (
                    <p className="text-sm text-muted-foreground">No time slots available</p>
                  )}
                </div>
              </div>
              
              <div className="space-y-2">
                <label className="text-sm font-medium">Assign Agent</label>
                <Select
                  value={selectedAgent?.id}
                  onValueChange={(id) => {
                    const agent = MOCK_AGENTS.find(a => a.id === id)
                    setSelectedAgent(agent ? { id: agent.id, name: agent.name } : null)
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select an agent" />
                  </SelectTrigger>
                  <SelectContent>
                    {MOCK_AGENTS.map(agent => (
                      <SelectItem key={agent.id} value={agent.id}>
                        {agent.name} ({agent.id})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsScheduleDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleScheduleCallback}
              disabled={!selectedAgent || !selectedTimeSlot}
            >
              <Video className="mr-2 h-4 w-4" />
              Schedule with Google Meet
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Callback Dialog */}
      <Dialog open={isCancelDialogOpen} onOpenChange={setIsCancelDialogOpen}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle>Cancel Callback</DialogTitle>
            <DialogDescription>
              Are you sure you want to cancel this callback? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          
          {selectedCallback && (
            <div className="space-y-4 py-4">
              <div className="p-3 border rounded-lg bg-muted/50">
                <div className="font-medium">{selectedCallback.customer_name}</div>
                <div className="text-sm text-muted-foreground">
                  Status: {getStatusLabel(selectedCallback.status)}
                </div>
                <div className="text-sm text-muted-foreground">
                  Scheduled: {selectedCallback.scheduled_start_time ? parseISODate(selectedCallback.scheduled_start_time).date : 'Not scheduled'}
                </div>
              </div>
              
              <div className="space-y-2">
                <label htmlFor="cancel_reason" className="text-sm font-medium">
                  Reason for Cancellation
                </label>
                <Input
                  id="cancel_reason"
                  value={cancelReason}
                  onChange={(e) => setCancelReason(e.target.value)}
                  placeholder="Enter reason for cancellation"
                />
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCancelDialogOpen(false)}>
              Keep Callback
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelCallback}
              disabled={!cancelReason}
            >
              <XCircle className="mr-2 h-4 w-4" />
              Cancel Callback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Complete Callback Dialog */}
      <Dialog open={isCompleteDialogOpen} onOpenChange={setIsCompleteDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Complete Callback Meeting</DialogTitle>
            <DialogDescription>
              Mark this callback as completed and add meeting notes
            </DialogDescription>
          </DialogHeader>
          
          {selectedCallback && (
            <div className="space-y-4 py-4">
              <div className="p-3 border rounded-lg bg-muted/50">
                <div className="font-medium">{selectedCallback.customer_name}</div>
                <div className="text-sm text-muted-foreground">
                  {selectedCallback.assigned_agent_name && `Agent: ${selectedCallback.assigned_agent_name}`}
                </div>
                <div className="text-sm text-muted-foreground">
                  {selectedCallback.meet_link && (
                    <a href={selectedCallback.meet_link} target="_blank" className="text-primary underline">
                      View Meeting
                    </a>
                  )}
                </div>
              </div>
              
              <div className="space-y-2">
                <label htmlFor="completion_outcome" className="text-sm font-medium">
                  Outcome
                </label>
                <Select
                  value={completionOutcome}
                  onValueChange={setCompletionOutcome}
                >
                  <SelectTrigger id="completion_outcome">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="success">Success - Converted</SelectItem>
                    <SelectItem value="discussion">Success - Discussion Only</SelectItem>
                    <SelectItem value="followup">Requires Follow-up</SelectItem>
                    <SelectItem value="no_interest">No Interest</SelectItem>
                    <SelectItem value="technical_issue">Technical Issue</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <label htmlFor="completion_notes" className="text-sm font-medium">
                  Meeting Notes
                </label>
                <Input
                  id="completion_notes"
                  value={completionNotes}
                  onChange={(e) => setCompletionNotes(e.target.value)}
                  placeholder="Summary of the meeting, key points discussed, next steps..."
                />
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsCompleteDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleCompleteCallback}
              disabled={!completionNotes}
            >
              <CheckCircle className="mr-2 h-4 w-4" />
              Mark as Completed
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Reschedule Callback Dialog */}
      <Dialog open={isRescheduleDialogOpen} onOpenChange={setIsRescheduleDialogOpen}>
        <DialogContent className="sm:max-w-[600px]">
          <DialogHeader>
            <DialogTitle>Reschedule Callback</DialogTitle>
            <DialogDescription>
              Change the date and time for this callback meeting
            </DialogDescription>
          </DialogHeader>
          
          {selectedCallback && (
            <div className="space-y-4 py-4">
              <div className="p-3 border rounded-lg bg-muted/50">
                <div className="font-medium">{selectedCallback.customer_name}</div>
                <div className="text-sm text-muted-foreground">
                  Current: {selectedCallback.scheduled_start_time ? 
                    `${format(new Date(selectedCallback.scheduled_start_time), 'PPpp')}` : 'Not scheduled'}
                </div>
              </div>
              
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <label htmlFor="reschedule_date" className="text-sm font-medium">
                    New Date
                  </label>
                  <Input
                    id="reschedule_date"
                    type="date"
                    value={rescheduleData.new_date}
                    onChange={(e) => setRescheduleData({...rescheduleData, new_date: e.target.value})}
                    min={format(new Date(), 'yyyy-MM-dd')}
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="reschedule_reason" className="text-sm font-medium">
                    Reason
                  </label>
                  <Input
                    id="reschedule_reason"
                    value={rescheduleData.reason}
                    onChange={(e) => setRescheduleData({...rescheduleData, reason: e.target.value})}
                    placeholder="Why reschedule?"
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="reschedule_start" className="text-sm font-medium">
                    Start Time
                  </label>
                  <Input
                    id="reschedule_start"
                    type="time"
                    value={rescheduleData.new_start_time}
                    onChange={(e) => setRescheduleData({...rescheduleData, new_start_time: e.target.value})}
                  />
                </div>
                <div className="space-y-2">
                  <label htmlFor="reschedule_end" className="text-sm font-medium">
                    End Time
                  </label>
                  <Input
                    id="reschedule_end"
                    type="time"
                    value={rescheduleData.new_end_time}
                    onChange={(e) => setRescheduleData({...rescheduleData, new_end_time: e.target.value})}
                  />
                </div>
              </div>
            </div>
          )}
          
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsRescheduleDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleRescheduleCallback}
              disabled={!rescheduleData.new_date || !rescheduleData.new_start_time || !rescheduleData.new_end_time || !rescheduleData.reason}
            >
              <RefreshCw className="mr-2 h-4 w-4" />
              Reschedule Callback
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

export default CallbacksPanel