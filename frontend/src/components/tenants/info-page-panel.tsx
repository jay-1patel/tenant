import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Check, ListTree, MessageSquareQuote, Pencil, Send, X } from 'lucide-react'
import { useAction } from '@/lib/hooks'
import { useAuth } from '@/lib/auth'
import { tenantsApi } from '@/lib/tenants'
import type { IntentSpec } from '@/lib/types'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Textarea } from '@/components/ui/input'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tags'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { useResolved } from '@/components/tenants/hooks'

/**
 * The informational pages of the software & IT vertical — projects,
 * technologies, careers, benefits. Each is one intent with answer text: no
 * flow, no backend service, the text is the whole page. The panel reads what
 * the bot answers today (the resolved profile), edits it into the working
 * draft and publishes, the same save-draft/publish contract as the profile
 * editor.
 */

export type InfoPageId = 'projects' | 'technologies' | 'careers' | 'benefits'

const PAGES: Record<
  InfoPageId,
  { title: string; description: string; permission: string; subject: string }
> = {
  projects: {
    title: 'Projects',
    description:
      'What the bot answers when a customer asks about your past work, case studies or clients.',
    permission: 'manage_projects',
    subject: 'your past work and case studies',
  },
  technologies: {
    title: 'Technologies',
    description:
      'What the bot answers when a customer asks about your tech stack, tools or languages.',
    permission: 'manage_technologies',
    subject: 'your tech stack',
  },
  careers: {
    title: 'Careers',
    description:
      'What the bot answers when a customer asks about hiring, vacancies or internships.',
    permission: 'manage_careers',
    subject: 'openings and hiring',
  },
  benefits: {
    title: 'Benefits',
    description:
      'What the bot answers when a customer asks why they should work with you.',
    permission: 'manage_benefits',
    subject: 'why teams choose you',
  },
}

interface FormShape {
  answer: string
  keywords: string[]
  enabled: boolean
}

export function InfoPagePanel({ tenantId, page }: { tenantId: string; page: InfoPageId }) {
  const spec = PAGES[page]
  const { data, loading, error, reload } = useResolved(tenantId)
  const { can, identity } = useAuth()
  const isSuperAdmin = identity?.role === 'super_admin'
  const action = useAction()
  const toast = useToast()
  const canEdit = can(spec.permission)

  const [editing, setEditing] = useState(false)
  const [form, setForm] = useState<FormShape | null>(null)
  const [warnings, setWarnings] = useState<string[]>([])
  const [draftSaved, setDraftSaved] = useState(false)

  const intent = useMemo(() => findIntent(data, page), [data, page])
  const menuButton = useMemo(
    () => (data?.menu.buttons ?? []).find((b) => b.intent === page) ?? null,
    [data, page],
  )
  const isActive = data?.active_intents.some((i) => i.name === page) ?? false

  useEffect(() => {
    if (!intent) return
    setForm(toForm(intent))
    setDraftSaved(false)
  }, [intent])

  if (loading) return <LoadingBlock label={`Loading ${spec.title.toLowerCase()}…`} />
  if (error) {
    return (
      <div>
        <PageHeader title={spec.title} description={spec.description} />
        <Alert tone="danger" title="Could not load the page">
          {error}
        </Alert>
      </div>
    )
  }
  if (!intent || !form) {
    return (
      <div>
        <PageHeader title={spec.title} description={spec.description} />
        <Alert tone="warning" title="No answer configured">
          This tenant's profile has no <code>{page}</code> intent, so the bot never
          answers questions about {spec.subject}. It has to come from the vertical
          defaults or a published profile version first.
        </Alert>
      </div>
    )
  }

  const dirty = JSON.stringify(form) !== JSON.stringify(toForm(intent))

  const save = async (thenPublish: boolean) => {
    const saved = await action.run(() =>
      tenantsApi.saveIntent(tenantId, page, {
        answer: form.answer,
        keywords: form.keywords,
        enabled: form.enabled,
      }),
    )
    if (!saved) return
    setWarnings(saved.validation ?? [])
    setDraftSaved(true)
    if (!thenPublish) {
      toast.push('Draft saved. Nothing is live until you publish.')
      return
    }
    if ((saved.validation ?? []).length) {
      toast.push('Draft has validation warnings — review them before publishing.', 'error')
      return
    }
    const published = await action.run(() => tenantsApi.publish(tenantId))
    if (published) {
      if (published.status === 'pending_approval') {
        toast.push(published.message ?? 'Change sent for super admin approval.')
      } else {
        toast.push(`Published version ${published.version}`)
      }
      setEditing(false)
      setDraftSaved(false)
      reload()
    }
  }

  return (
    <div>
      <PageHeader
        title={spec.title}
        description={spec.description}
        meta={
          <>
            <Badge tone={isActive ? 'success' : 'muted'}>
              {isActive ? 'the bot answers this' : 'hidden from the bot'}
            </Badge>
            {menuButton ? (
              <Badge tone="accent">
                menu row: “{menuButton.title}” in {menuButton.section}
              </Badge>
            ) : (
              <Badge tone="warning">no menu row points here</Badge>
            )}
          </>
        }
        actions={
          !editing ? (
            canEdit ? (
              <Button
                variant="primary"
                icon={<Pencil className="h-4 w-4" />}
                onClick={() => setEditing(true)}
              >
                Edit answer
              </Button>
            ) : undefined
          ) : (
            <>
              <Button
                variant="ghost"
                icon={<X className="h-4 w-4" />}
                onClick={() => {
                  setEditing(false)
                  setForm(toForm(intent))
                  setWarnings([])
                }}
              >
                Cancel
              </Button>
              <Button
                variant="secondary"
                icon={<Check className="h-4 w-4" />}
                loading={action.busy}
                disabled={!dirty}
                onClick={() => save(false)}
              >
                Save draft
              </Button>
              <Button
                variant="primary"
                icon={<Send className="h-4 w-4" />}
                loading={action.busy}
                disabled={!dirty}
                onClick={() => save(true)}
              >
                {isSuperAdmin ? 'Save & publish' : 'Submit for approval'}
              </Button>
            </>
          )
        }
      />

      {!canEdit && (
        <Alert tone="warning" title="Read-only" className="mb-4">
          Editing this page needs the <strong>{spec.permission}</strong> permission —
          a super admin can grant it under Team &amp; permissions.
        </Alert>
      )}
      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}
      {warnings.length > 0 && (
        <Alert tone="warning" title="Draft saved with warnings" className="mb-4">
          <ul className="list-disc space-y-1 pl-4">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Alert>
      )}
      {draftSaved && !editing && (
        <Alert tone="info" title="Saved to the working draft" className="mb-4">
          The draft carries a newer answer for this page. It goes live when the draft
          is published — from here, or from the Profile or Versions screen.
        </Alert>
      )}

      {editing && form ? (
        <Card>
          <CardHeader
            title={`Edit the ${spec.title.toLowerCase()} answer`}
            description="Saving writes the working draft. Publishing validates it, versions it and swaps the live profile — publishing is the only thing the bot ever sees."
            actions={
              <Badge tone={form.enabled ? 'success' : 'muted'}>
                {form.enabled ? 'will answer' : 'will not answer'}
              </Badge>
            }
          />
          <CardBody className="space-y-5">
            <Textarea
              label="Answer text"
              rows={8}
              value={form.answer}
              onChange={(e) => setForm((f) => (f ? { ...f, answer: e.target.value } : f))}
              hint='What the bot sends, verbatim. One bullet per line starting with "• "; *stars* make a word bold. Leave empty to stop answering directly — questions then fall through to the knowledge-base pipeline.'
            />
            <TagInput
              value={form.keywords}
              onChange={(keywords) => setForm((f) => (f ? { ...f, keywords } : f))}
              placeholder="Add a keyword and press Enter"
            />
            <p className="hint">
              Phrases that route a question to this answer. The classifier only ever
              picks intents the tenant has switched on.
            </p>
            <Switch
              checked={form.enabled}
              onChange={(enabled) => setForm((f) => (f ? { ...f, enabled } : f))}
              label="The bot answers questions about this page"
              description="Turn off to keep the text but stop the intent from winning — the menu row disappears too."
            />
            <p className="text-2xs text-slate-500">
              {dirty ? 'Unsaved changes will be written as a draft, not published.' : 'No changes yet.'}
            </p>
          </CardBody>
        </Card>
      ) : (
        <div className="grid gap-4 lg:grid-cols-3">
          <Card className="lg:col-span-2">
            <CardHeader
              title="What the bot replies"
              description={`The live answer for questions about ${spec.subject}.`}
              icon={<MessageSquareQuote className="h-4 w-4" />}
            />
            <CardBody>
              <AnswerPreview text={intent.answer ?? ''} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader
              title="How customers reach it"
              description="Routing and entry points."
              icon={<ListTree className="h-4 w-4" />}
            />
            <CardBody className="space-y-4">
              {intent.keywords?.length ? (
                <div>
                  <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                    Keywords
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {intent.keywords.map((k) => (
                      <Badge key={k} tone="neutral">
                        {k}
                      </Badge>
                    ))}
                  </div>
                </div>
              ) : (
                <p className="text-xs text-slate-500">No keywords routed to this answer.</p>
              )}
              {intent.examples?.length ? (
                <div>
                  <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                    Phrases it answers
                  </p>
                  <ul className="space-y-1">
                    {intent.examples.map((ex) => (
                      <li key={ex} className="text-xs italic leading-relaxed text-slate-600">
                        “{ex}”
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div>
                <p className="mb-1.5 text-2xs font-semibold uppercase tracking-wider text-slate-500">
                  Menu row
                </p>
                {menuButton ? (
                  <p className="text-xs leading-relaxed text-slate-400">
                    “{menuButton.title}” in the {menuButton.section} section of the
                    bot's menu{isActive ? '' : ' — currently hidden because the intent is off'}.
                  </p>
                ) : (
                  <p className="text-xs leading-relaxed text-slate-500">
                    No menu button points here — customers only reach this answer by
                    asking in their own words.
                  </p>
                )}
              </div>
            </CardBody>
          </Card>
        </div>
      )}
    </div>
  )
}

function findIntent(
  data: ReturnType<typeof useResolved>['data'],
  page: InfoPageId,
): IntentSpec | null {
  if (!data) return null
  return [...data.active_intents, ...data.inactive_intents].find((i) => i.name === page) ?? null
}

function toForm(intent: IntentSpec): FormShape {
  return {
    answer: intent.answer ?? '',
    keywords: [...(intent.keywords ?? [])],
    enabled: intent.enabled ?? true,
  }
}

/** Render the WhatsApp-style answer: "• " bullets, *bold* segments. */
function AnswerPreview({ text }: { text: string }) {
  const lines = text
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean)

  if (!lines.length) {
    return (
      <EmptyState
        title="No answer configured"
        description="Questions about this page fall through to the knowledge-base pipeline instead of a fixed reply."
        icon={<MessageSquareQuote className="h-6 w-6" />}
      />
    )
  }

  return (
    <ul className="space-y-2">
      {lines.map((line, i) => {
        const bullet = line.startsWith('•')
        const body = bullet ? line.slice(1).trim() : line
        return (
          <li key={i} className="flex gap-2.5 text-sm leading-relaxed text-slate-300">
            {bullet && <span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-accent-400" />}
            <span>{renderInline(body)}</span>
          </li>
        )
      })}
    </ul>
  )
}

function renderInline(text: string): ReactNode[] {
  return text.split(/\*([^*]+)\*/g).map((part, i) =>
    i % 2 === 1 ? (
      <strong key={i} className="font-semibold text-slate-100">
        {part}
      </strong>
    ) : (
      part
    ),
  )
}
