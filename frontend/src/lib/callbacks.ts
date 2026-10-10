/**
 * Callback Booking API Client for Chatbot2.
 *
 * This module provides TypeScript types and functions for interacting with
 * the callback booking API, including:
 * - Creating and managing callback requests
 * - Scheduling meetings with Google Meet
 * - Managing time slots and agent availability
 * - Analytics and reporting
 */

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

export const CALLBACK_STATUSES = [
  'pending',
  'confirmed', 
  'scheduled',
  'in_progress',
  'completed',
  'cancelled',
  'no_show'
] as const

export const CALLBACK_TYPES = [
  'sales',
  'support',
  'technical',
  'general', 
  'follow_up'
] as const

export const CALLBACK_PRIORITIES = [
  'low',
  'medium',
  'high',
  'urgent'
] as const

// Types
export type CallbackStatus = (typeof CALLBACK_STATUSES)[number]
export type CallbackType = (typeof CALLBACK_TYPES)[number]
export type CallbackPriority = (typeof CALLBACK_PRIORITIES)[number]

export interface CallbackRequest {
  id: string
  tenant_id: string
  wa_id: string
  customer_name: string
  customer_email?: string | null
  customer_phone?: string | null
  callback_type: CallbackType
  priority: CallbackPriority
  preferred_time?: string | null
  preferred_date?: string | null
  time_slot?: string | null
  timezone: string
  purpose: string
  additional_info: string
  assigned_agent_id?: string | null
  assigned_agent_name?: string | null
  meet_link?: string | null
  calendar_event_id?: string | null
  status: CallbackStatus
  scheduled_start_time?: string | null
  scheduled_end_time?: string | null
  created_at: string
  updated_at: string
  reminder_sent: boolean
  notification_sent: boolean
  metadata: Record<string, unknown>
}

export interface CreateCallbackRequest {
  customer_name: string
  wa_id: string
  callback_type?: CallbackType
  purpose?: string
  customer_email?: string | null
  customer_phone?: string | null
  priority?: CallbackPriority
  preferred_date?: string | null
  preferred_time?: string | null
  additional_info?: string
  metadata?: Record<string, unknown>
}

export interface UpdateCallbackRequest {
  customer_name?: string
  customer_email?: string | null
  customer_phone?: string | null
  callback_type?: CallbackType
  purpose?: string
  priority?: CallbackPriority
  preferred_date?: string | null
  preferred_time?: string | null
  additional_info?: string
  assigned_agent_id?: string | null
  assigned_agent_name?: string | null
  status?: CallbackStatus
  notes?: string
  metadata?: Record<string, unknown>
}

export interface ScheduleCallbackRequest {
  agent_id: string
  agent_name: string
  start_time: string  // ISO format
  end_time: string    // ISO format
  time_slot_id?: string | null
  send_notifications: boolean
}

export interface TimeSlot {
  id: string
  date: string
  start_time: string
  end_time: string
  display_text: string
  available: boolean
  duration_minutes: number
}

export interface AgentAvailability {
  id: number
  agent_id: string
  agent_name: string
  date: string
  start_time: string
  end_time: string
  is_available: boolean
  is_booked: boolean
  callback_id?: string | null
}

export interface CallbackStats {
  tenant_id: string
  period: {
    days: number
    start_date: string
    end_date: string
  }
  total_callbacks: number
  status_distribution: Record<CallbackStatus, number>
  type_distribution: Record<CallbackType, number>
  daily_counts: Array<{ date: string; count: number }>
  average_resolution_time_days?: number | null
  completion_rate: number
  cancelation_rate: number
}

export interface CallbackSummary {
  callback_id: string
  meeting_notes: string
  outcome: string
  follow_up_required: boolean
  follow_up_notes?: string | null
  created_at: string
}

export interface CancelCallbackRequest {
  reason: string
  notify_customer: boolean
  notify_agent: boolean
  cancellation_notes?: string | null
}

export interface RescheduleCallbackRequest {
  new_start_time: string  // ISO format
  new_end_time: string    // ISO format
  new_date?: string | null // YYYY-MM-DD
  reason: string
  notify_participants: boolean
}

export interface CompleteCallbackRequest {
  meeting_notes: string
  outcome: string
  follow_up_required: boolean
  follow_up_notes?: string | null
}

export interface Agent {
  id: string
  name: string
  email?: string | null
  phone?: string | null
  specialization?: string | null
  is_active: boolean
  current_callbacks: number
  max_concurrent_callbacks: number
}

// API Functions
const CALLBACK_API_BASE = '/api/tenants'

/**
 * Create a new callback request
 */
export async function createCallback(
  tenantId: string,
  data: CreateCallbackRequest
): Promise<{ ok: boolean; callback_id: string; status: CallbackStatus; message: string }> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to create callback: ${error}`)
  }
  
  return response.json()
}

/**
 * List all callbacks for a tenant
 */
export async function listCallbacks(
  tenantId: string,
  params: {
    status?: CallbackStatus | null
    wa_id?: string | null
    agent_id?: string | null
    date_from?: string | null
    date_to?: string | null
    limit?: number
    offset?: number
  } = {}
): Promise<{
  ok: boolean
  tenant_id: string
  callbacks: CallbackRequest[]
  total_count: number
  limit: number
  offset: number
}> {
  const query = new URLSearchParams()
  if (params.status) query.set('status', params.status)
  if (params.wa_id) query.set('wa_id', params.wa_id)
  if (params.agent_id) query.set('agent_id', params.agent_id)
  if (params.date_from) query.set('date_from', params.date_from)
  if (params.date_to) query.set('date_to', params.date_to)
  if (params.limit) query.set('limit', params.limit.toString())
  if (params.offset) query.set('offset', params.offset.toString())
  
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks?${query.toString()}`)
  
  if (!response.ok) {
    throw new Error(`Failed to list callbacks: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Get a specific callback by ID
 */
export async function getCallback(
  tenantId: string,
  callbackId: string
): Promise<{ ok: boolean; callback: CallbackRequest }> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}`)
  
  if (!response.ok) {
    throw new Error(`Callback not found: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Update a callback
 */
export async function updateCallback(
  tenantId: string,
  callbackId: string,
  data: UpdateCallbackRequest
): Promise<{
  ok: boolean
  callback_id: string
  status: CallbackStatus
  message: string
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to update callback: ${error}`)
  }
  
  return response.json()
}

/**
 * Schedule a callback with Google Meet
 */
export async function scheduleCallback(
  tenantId: string,
  callbackId: string,
  data: ScheduleCallbackRequest
): Promise<{
  ok: boolean
  callback_id: string
  meet_link: string
  calendar_event_id: string
  status: CallbackStatus
  start_time: string
  end_time: string
  agent: { id: string; name: string }
  message: string
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}/schedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to schedule callback: ${error}`)
  }
  
  return response.json()
}

/**
 * Cancel a callback
 */
export async function cancelCallback(
  tenantId: string,
  callbackId: string,
  data: CancelCallbackRequest
): Promise<{
  ok: boolean
  callback_id: string
  status: CallbackStatus
  message: string
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}/cancel`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to cancel callback: ${error}`)
  }
  
  return response.json()
}

/**
 * Complete a callback meeting
 */
export async function completeCallback(
  tenantId: string,
  callbackId: string,
  data: CompleteCallbackRequest
): Promise<{
  ok: boolean
  callback_id: string
  status: CallbackStatus
  message: string
  summary: CallbackSummary
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}/complete`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to complete callback: ${error}`)
  }
  
  return response.json()
}

/**
 * Reschedule a callback
 */
export async function rescheduleCallback(
  tenantId: string,
  callbackId: string,
  data: RescheduleCallbackRequest
): Promise<{
  ok: boolean
  callback_id: string
  meet_link: string
  calendar_event_id: string
  new_start_time: string
  new_end_time: string
  message: string
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}/reschedule`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to reschedule callback: ${error}`)
  }
  
  return response.json()
}

/**
 * Get available time slots for a specific date
 */
export async function getTimeSlots(
  tenantId: string,
  date: string,
  agentId?: string | null,
  durationMinutes?: number | null
): Promise<{
  ok: boolean
  date: string
  agent_id?: string | null
  time_slots: TimeSlot[]
  total_available: number
}> {
  const query = new URLSearchParams()
  query.set('date', date)
  if (agentId) query.set('agent_id', agentId)
  if (durationMinutes) query.set('duration_minutes', durationMinutes.toString())
  
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/time-slots?${query.toString()}`)
  
  if (!response.ok) {
    throw new Error(`Failed to get time slots: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Get callback summary
 */
export async function getCallbackSummary(
  tenantId: string,
  callbackId: string
): Promise<{
  ok: boolean
  callback_id: string
  summary: Record<string, unknown>
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/${callbackId}/summary`)
  
  if (!response.ok) {
    throw new Error(`Failed to get callback summary: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Get upcoming callbacks
 */
export async function getUpcomingCallbacks(
  tenantId: string,
  daysAhead: number = 7,
  limit: number = 50
): Promise<{
  ok: boolean
  tenant_id: string
  upcoming_callbacks: CallbackRequest[]
  total: number
  days_ahead: number
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/upcoming?days_ahead=${daysAhead}&limit=${limit}`)
  
  if (!response.ok) {
    throw new Error(`Failed to get upcoming callbacks: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Get callback statistics
 */
export async function getCallbackStats(
  tenantId: string,
  days: number = 30
): Promise<CallbackStats> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/stats?days=${days}`)
  
  if (!response.ok) {
    throw new Error(`Failed to get callback stats: ${response.statusText}`)
  }
  
  return response.json()
}

/**
 * Test Google Meet integration
 */
export async function testGoogleMeet(tenantId: string): Promise<{
  ok: boolean
  test_successful: boolean
  event_id?: string
  meet_link?: string
  message: string
}> {
  const response = await fetch(`${CALLBACK_API_BASE}/${tenantId}/callbacks/meet-test`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' }
  })
  
  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Failed to test Google Meet: ${error}`)
  }
  
  return response.json()
}

// React Query hooks

/**
 * Hook for listing callbacks
 */
export function useCallbacks(
  tenantId: string,
  params: {
    status?: CallbackStatus | null
    wa_id?: string | null
    agent_id?: string | null
    limit?: number
    offset?: number
  } = {}
) {
  return useQuery({
    queryKey: ['callbacks', tenantId, params],
    queryFn: () => listCallbacks(tenantId, params)
  })
}

/**
 * Hook for getting a specific callback
 */
export function useCallback(
  tenantId: string,
  callbackId: string
) {
  return useQuery({
    queryKey: ['callback', tenantId, callbackId],
    queryFn: () => getCallback(tenantId, callbackId),
    enabled: !!tenantId && !!callbackId
  })
}

/**
 * Hook for getting upcoming callbacks
 */
export function useUpcomingCallbacks(
  tenantId: string,
  daysAhead: number = 7,
  limit: number = 50
) {
  return useQuery({
    queryKey: ['upcoming-callbacks', tenantId, daysAhead, limit],
    queryFn: () => getUpcomingCallbacks(tenantId, daysAhead, limit)
  })
}

/**
 * Hook for getting time slots
 */
export function useTimeSlots(
  tenantId: string,
  date: string,
  agentId?: string | null,
  durationMinutes?: number | null
) {
  return useQuery({
    queryKey: ['time-slots', tenantId, date, agentId, durationMinutes],
    queryFn: () => getTimeSlots(tenantId, date, agentId, durationMinutes),
    enabled: !!tenantId && !!date
  })
}

/**
 * Hook for getting callback stats
 */
export function useCallbackStats(
  tenantId: string,
  days: number = 30
) {
  return useQuery({
    queryKey: ['callback-stats', tenantId, days],
    queryFn: () => getCallbackStats(tenantId, days)
  })
}

/**
 * Hook for creating a callback
 */
export function useCreateCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ tenantId, data }: { tenantId: string; data: CreateCallbackRequest }) => 
      createCallback(tenantId, data),
    onSuccess: (result, { tenantId }) => {
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['callback-stats', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
    }
  })
}

/**
 * Hook for updating a callback
 */
export function useUpdateCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      callbackId, 
      data 
    }: { 
      tenantId: string; 
      callbackId: string; 
      data: UpdateCallbackRequest 
    }) => updateCallback(tenantId, callbackId, data),
    onSuccess: (result, { tenantId, callbackId }) => {
      queryClient.invalidateQueries({ queryKey: ['callback', tenantId, callbackId] })
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
    }
  })
}

/**
 * Hook for scheduling a callback
 */
export function useScheduleCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      callbackId, 
      data 
    }: { 
      tenantId: string; 
      callbackId: string; 
      data: ScheduleCallbackRequest 
    }) => scheduleCallback(tenantId, callbackId, data),
    onSuccess: (result, { tenantId, callbackId }) => {
      queryClient.invalidateQueries({ queryKey: ['callback', tenantId, callbackId] })
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['callback-stats', tenantId] })
    }
  })
}

/**
 * Hook for cancelling a callback
 */
export function useCancelCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      callbackId, 
      data 
    }: { 
      tenantId: string; 
      callbackId: string; 
      data: CancelCallbackRequest 
    }) => cancelCallback(tenantId, callbackId, data),
    onSuccess: (result, { tenantId, callbackId }) => {
      queryClient.invalidateQueries({ queryKey: ['callback', tenantId, callbackId] })
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['callback-stats', tenantId] })
    }
  })
}

/**
 * Hook for completing a callback
 */
export function useCompleteCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      callbackId, 
      data 
    }: { 
      tenantId: string; 
      callbackId: string; 
      data: CompleteCallbackRequest 
    }) => completeCallback(tenantId, callbackId, data),
    onSuccess: (result, { tenantId, callbackId }) => {
      queryClient.invalidateQueries({ queryKey: ['callback', tenantId, callbackId] })
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['callback-stats', tenantId] })
    }
  })
}

/**
 * Hook for rescheduling a callback
 */
export function useRescheduleCallback() {
  const queryClient = useQueryClient()
  
  return useMutation({
    mutationFn: ({ 
      tenantId, 
      callbackId, 
      data 
    }: { 
      tenantId: string; 
      callbackId: string; 
      data: RescheduleCallbackRequest 
    }) => rescheduleCallback(tenantId, callbackId, data),
    onSuccess: (result, { tenantId, callbackId }) => {
      queryClient.invalidateQueries({ queryKey: ['callback', tenantId, callbackId] })
      queryClient.invalidateQueries({ queryKey: ['callbacks', tenantId] })
      queryClient.invalidateQueries({ queryKey: ['upcoming-callbacks', tenantId] })
    }
  })
}

// Utility functions

/**
 * Format a callback for display
 */
export function formatCallbackForDisplay(callback: CallbackRequest): {
  id: string
  status: CallbackStatus
  customer: {
    name: string
    email?: string | null
    phone?: string | null
    wa_id: string
  }
  callback: {
    type: CallbackType
    priority: CallbackPriority
    purpose?: string
    additional_info?: string
  }
  scheduling: {
    preferred_date?: string | null
    preferred_time?: string | null
    scheduled_start?: string | null
    scheduled_end?: string | null
    timezone: string
  }
  assignment: {
    agent_id?: string | null
    agent_name?: string | null
  }
  meeting: {
    meet_link?: string | null
    calendar_event_id?: string | null
  }
  timestamps: {
    created_at: string
    updated_at: string
  }
} {
  return {
    id: callback.id,
    status: callback.status,
    customer: {
      name: callback.customer_name,
      email: callback.customer_email,
      phone: callback.customer_phone,
      wa_id: callback.wa_id
    },
    callback: {
      type: callback.callback_type,
      priority: callback.priority,
      purpose: callback.purpose || undefined,
      additional_info: callback.additional_info || undefined
    },
    scheduling: {
      preferred_date: callback.preferred_date,
      preferred_time: callback.preferred_time,
      scheduled_start: callback.scheduled_start_time,
      scheduled_end: callback.scheduled_end_time,
      timezone: callback.timezone
    },
    assignment: {
      agent_id: callback.assigned_agent_id,
      agent_name: callback.assigned_agent_name
    },
    meeting: {
      meet_link: callback.meet_link,
      calendar_event_id: callback.calendar_event_id
    },
    timestamps: {
      created_at: callback.created_at,
      updated_at: callback.updated_at
    }
  }
}

/**
 * Get status color for badges
 */
export function getStatusColor(status: CallbackStatus): string {
  const colors: Record<CallbackStatus, string> = {
    pending: 'bg-yellow-100 text-yellow-800',
    confirmed: 'bg-blue-100 text-blue-800',
    scheduled: 'bg-green-100 text-green-800',
    in_progress: 'bg-purple-100 text-purple-800',
    completed: 'bg-gray-100 text-gray-800',
    cancelled: 'bg-red-100 text-red-800',
    no_show: 'bg-orange-100 text-orange-800'
  }
  return colors[status] || 'bg-gray-100 text-gray-800'
}

/**
 * Get status label for display
 */
export function getStatusLabel(status: CallbackStatus): string {
  const labels: Record<CallbackStatus, string> = {
    pending: 'Pending',
    confirmed: 'Confirmed',
    scheduled: 'Scheduled',
    in_progress: 'In Progress',
    completed: 'Completed',
    cancelled: 'Cancelled',
    no_show: 'No Show'
  }
  return labels[status] || status
}

/**
 * Get priority color
 */
export function getPriorityColor(priority: CallbackPriority): string {
  const colors: Record<CallbackPriority, string> = {
    low: 'bg-gray-100 text-gray-800',
    medium: 'bg-blue-100 text-blue-800',
    high: 'bg-orange-100 text-orange-800',
    urgent: 'bg-red-100 text-red-800'
  }
  return colors[priority] || 'bg-gray-100 text-gray-800'
}

/**
 * Get type label
 */
export function getTypeLabel(type: CallbackType): string {
  const labels: Record<CallbackType, string> = {
    sales: 'Sales Consultation',
    support: 'Technical Support',
    technical: 'Technical Discussion',
    general: 'General Inquiry',
    follow_up: 'Follow-up'
  }
  return labels[type] || type
}

/**
 * Check if a callback can be scheduled
 */
export function canScheduleCallback(callback: CallbackRequest): boolean {
  return callback.status === 'pending' || callback.status === 'confirmed'
}

/**
 * Check if a callback can be cancelled
 */
export function canCancelCallback(callback: CallbackRequest): boolean {
  return callback.status !== 'completed' && callback.status !== 'cancelled'
}

/**
 * Check if a callback can be rescheduled
 */
export function canRescheduleCallback(callback: CallbackRequest): boolean {
  return callback.status === 'scheduled' || callback.status === 'confirmed'
}

/**
 * Check if a callback can be marked as completed
 */
export function canCompleteCallback(callback: CallbackRequest): boolean {
  return callback.status === 'scheduled' || callback.status === 'in_progress'
}

/**
 * Format date and time for display
 */
export function formatDateTimeForDisplay(
  dateStr: string | null | undefined,
  timeStr: string | null | undefined,
  timezone: string = 'Asia/Kolkata'
): string {
  if (!dateStr && !timeStr) return 'N/A'
  
  try {
    const date = dateStr || ''
    const time = timeStr || ''
    
    if (date && time) {
      return `${new Date(date).toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric',
        timezone 
      })} at ${formatTime(time)} ${timezone}`
    } else if (date) {
      return new Date(date).toLocaleDateString('en-US', { 
        year: 'numeric', 
        month: 'short', 
        day: 'numeric',
        timezone 
      })
    } else if (time) {
      return `${formatTime(time)} ${timezone}`
    }
    return 'N/A'
  } catch {
    return 'N/A'
  }
}

/**
 * Format time in HH:MM format
 */
export function formatTime(timeStr: string): string {
  if (!timeStr) return ''
  try {
    const [hours, minutes] = timeStr.split(':')
    const hour = parseInt(hours)
    const minute = minutes || '00'
    const ampm = hour >= 12 ? 'PM' : 'AM'
    const hour12 = hour % 12 || 12
    return `${hour12}:${minute} ${ampm}`
  } catch {
    return timeStr
  }
}

/**
 * Parse ISO date string to display format
 */
export function parseISODate(isoStr: string): { date: string; time: string } {
  if (!isoStr) return { date: 'N/A', time: 'N/A' }
  
  try {
    const date = new Date(isoStr)
    const formattedDate = date.toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric'
    })
    
    const hours = date.getHours()
    const minutes = date.getMinutes()
    const ampm = hours >= 12 ? 'PM' : 'AM'
    const hour12 = hours % 12 || 12
    const formattedTime = `${hour12}:${minutes.toString().padStart(2, '0')} ${ampm}`
    
    return {
      date: formattedDate,
      time: formattedTime
    }
  } catch {
    return { date: 'N/A', time: 'N/A' }
  }
}