import { useEffect, useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ListPlus, Pencil, Save, Send, Trash2, X } from 'lucide-react'
import { tenantsApi } from '@/lib/tenants'
import { useAction } from '@/lib/hooks'
import { slugify } from '@/lib/profile'
import { FEATURE_FLAGS, type FeatureFlag, type IntentSpec, type MenuButton, type MenuSpec, type ProfileSnapshot } from '@/lib/types'
import { FEATURE_LABELS, getVertical } from '@/lib/verticals'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader, SectionTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Input, Textarea } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { TagInput } from '@/components/ui/tags'
import { Alert, EmptyState, LoadingBlock } from '@/components/ui/feedback'
import { PageHeader } from '@/components/layout/page-header'
import { useToast } from '@/components/ui/toast'
import { useAuth } from '@/lib/auth'
import { useTenantDetail } from './hooks'

type ButtonDraft = Omit<MenuButton, 'sort_order'> & { sort_order: number }

/** Select sentinel: the operator is creating a new informational page. */
const NEW_INTENT = '__new_page__'
const INTENT_ID_RE = /^[a-z][a-z0-9_]{0,39}$/

interface IntentEdit {
  answer: string
  keywords: string[]
}

const blankButton = (index: number): ButtonDraft => ({
  id: '',
  title: '',
  description: '',
  section: 'General',
  icon: '',
  sort_order: index,
  enabled: true,
  requires_feature: null,
  out_of_hours_only: false,
  flow: null,
  intent: null,
})

/**
 * Menu editor.
 *
 * Buttons are addressed by `id` at runtime — the flow runner and the routing
 * dispatcher switch on it exactly — so the id is required and must be unique.
 * Saving writes a draft; publishing is a separate, deliberate step, because the
 * bot only ever sees published profiles.
 */
export function MenuEditor({ tenantId, focusId }: { tenantId: string; focusId?: string | null }) {
  const detail = useTenantDetail(tenantId)
  const action = useAction()
  const toast = useToast()
  const { identity } = useAuth()
  const isSuperAdmin = identity?.role === 'super_admin'

  const [menu, setMenu] = useState<MenuSpec | null>(null)
  const [editingIndex, setEditingIndex] = useState<number | null>(null)
  const [draft, setDraft] = useState<ButtonDraft | null>(null)
  const [error, setError] = useState<string | null>(null)
  /**
   * Ids deleted in this editing session. Layers merge menu buttons *by id*, so a
   * deleted default has to be tombstoned with `__remove__` — dropping it from the
   * payload would just let the default come back on the next merge.
   */
  const [removed, setRemoved] = useState<string[]>([])
  /** The buttons as loaded, so we can tell an inherited value from a cleared one. */
  const [loaded, setLoaded] = useState<ButtonDraft[]>([])
  /**
   * Answer/keyword edits for the intent an option routes to — new pages
   * created in this session and tweaks to existing ones. Saved into the draft
   * on commit, before the menu itself.
   */
  const [intentEdits, setIntentEdits] = useState<Record<string, IntentEdit>>({})
  /** Names created in this session (they need `enabled: true` on first save). */
  const [newIntents, setNewIntents] = useState<string[]>([])
  const [newIntentName, setNewIntentName] = useState('')
  const [newNameTouched, setNewNameTouched] = useState(false)

  const effective = detail.data?.pending ?? detail.data?.effective ?? null

  useEffect(() => {
    if (effective?.menu) {
      const next = normaliseMenu(effective.menu)
      setMenu(next)
      setLoaded(next.buttons)
      setRemoved([])
      setIntentEdits({})
      setNewIntents([])
    }
  }, [effective])

  // Arriving from the sidebar with ?focus=<button id> opens that option directly.
  useEffect(() => {
    if (!focusId || !menu) return
    const index = menu.buttons.findIndex((b) => b.id === focusId)
    if (index === -1) return
    setDraft({ ...menu.buttons[index] })
    setEditingIndex(index)
  }, [focusId, menu])

  const flowNames = useMemo(
    () => (effective?.flows ?? []).map((f) => f.name).sort(),
    [effective],
  )
  const intentNames = useMemo(
    () => (effective?.intents ?? []).map((i) => i.name).sort(),
    [effective],
  )
  /** Every intent with its current answer/keywords, to prefill the editor. */
  const intentMap = useMemo(
    () => new Map<string, IntentSpec>((effective?.intents ?? []).map((i) => [i.name, i])),
    [effective],
  )
  /** Intent ids the option form can pick: existing ones plus this session's. */
  const intentOptions = useMemo(
    () =>
      Array.from(new Set([...intentNames, ...Object.keys(intentEdits), ...newIntents])).sort(),
    [intentNames, intentEdits, newIntents],
  )

  if (detail.loading) return <LoadingBlock label="Loading the menu…" />
  if (detail.error) {
    return (
      <Alert tone="danger" title="Could not load the menu">
        {detail.error}
      </Alert>
    )
  }
  if (!menu || !effective) {
    return (
      <Alert tone="warning" title="No effective profile">
        The merged profile could not be built, so there is no menu to edit.
      </Alert>
    )
  }

  const vertical = getVertical(effective.vertical)
  const buttons = [...menu.buttons].sort((a, b) => a.sort_order - b.sort_order)

  const setButtons = (next: ButtonDraft[]) => {
    setMenu({ ...menu, buttons: next.map((b, i) => ({ ...b, sort_order: i })) })
  }

  const commit = async (thenPublish: boolean) => {
    const clean = validate(menu, buttons)
    if (clean) {
      setError(clean)
      return
    }
    setError(null)
    // Intent pages ride along in the same draft: save the ones an option
    // actually references first (a half-written page whose option was
    // cancelled or deleted is skipped), then the menu — drafts accumulate,
    // so both land together and one publish makes them live.
    const referenced = new Set(
      buttons.map((b) => b.intent).filter((i): i is string => Boolean(i)),
    )
    const pending = Object.entries(intentEdits).filter(([name]) => referenced.has(name))
    for (const [name, edit] of pending) {
      const body: { answer?: string | null; keywords?: string[]; enabled?: boolean } = {
        answer: edit.answer,
        keywords: edit.keywords,
      }
      if (newIntents.includes(name)) body.enabled = true
      const ok = await action.run(() => tenantsApi.saveIntent(tenantId, name, body))
      if (!ok) return
    }
    const snapshot = {
      menu: {
        key: menu.key,
        header: menu.header,
        body: menu.body,
        footer: menu.footer,
        button_text: menu.button_text,
        buttons: [
          ...buttons.map((b, i) => ({ ...b, sort_order: i })),
          // Tombstones for anything deleted in this session.
          ...removed.map((id) => ({ id, __remove__: true })),
        ],
      },
    }
    const saved = await action.run(() => tenantsApi.saveDraft(tenantId, snapshot))
    if (!saved) return
    setIntentEdits({})
    setNewIntents([])
    if (!thenPublish) {
      toast.push('Menu saved as a draft. Publish to make it live.')
      return
    }
    if ((saved.validation ?? []).length) {
      setError(saved.validation.join(' '))
      return
    }
    const published = await action.run(() => tenantsApi.publish(tenantId))
    if (published) {
      if (published.status === 'pending_approval') {
        toast.push(published.message ?? 'Change sent for super admin approval.')
      } else {
        toast.push(`Menu published as version ${published.version}`)
      }
      detail.reload()
    }
  }

  /**
   * A `null` on the right-hand layer never clobbers a lower layer, so clearing an
   * inherited `requires_feature` / `flow` / `intent` will not stick. Say so
   * rather than letting the operator believe it did.
   */
  const uncleared = buttons.flatMap((button) => {
    const original = loaded.find((b) => b.id === button.id)
    if (!original) return []
    const notes: string[] = []
    if (original.requires_feature && !button.requires_feature) {
      notes.push(`${button.id}: "always show" will not clear the inherited "${FEATURE_LABELS[original.requires_feature as FeatureFlag]?.label ?? original.requires_feature}" requirement`)
    }
    if (original.flow && !button.flow) {
      notes.push(`${button.id}: the inherited flow "${original.flow}" stays`)
    }
    if (original.intent && !button.intent) {
      notes.push(`${button.id}: the inherited intent "${original.intent}" stays`)
    }
    return notes
  })

  const startAdd = () => {
    setDraft(blankButton(buttons.length))
    setEditingIndex(-1)
    setNewIntentName('')
    setNewNameTouched(false)
  }

  const startEdit = (index: number) => {
    setDraft({ ...buttons[index] })
    setEditingIndex(index)
  }

  const saveDraftButton = () => {
    if (!draft) return
    let button = draft
    if (draft.intent === NEW_INTENT) {
      const name = newIntentName.trim()
      if (!INTENT_ID_RE.test(name)) {
        setError(
          'The new page id must be lowercase letters, digits and underscores, starting with a letter (e.g. why_choose_us).',
        )
        return
      }
      if (intentNames.includes(name)) {
        setError(`"${name}" already exists as an intent — pick it from the list instead.`)
        return
      }
      button = { ...draft, intent: name }
      setNewIntents((current) => (current.includes(name) ? current : [...current, name]))
      // Even an untouched new page must reach the draft so the intent exists.
      setIntentEdits((prev) =>
        prev[name] ? prev : { ...prev, [name]: { answer: '', keywords: [] } },
      )
    }
    const problem = validateButton(button, buttons.filter((_, i) => i !== editingIndex))
    if (problem) {
      setError(problem)
      return
    }
    const next = [...buttons]
    if (editingIndex === -1 || editingIndex === null) next.push(button)
    else next[editingIndex] = button
    setButtons(next)
    // Re-adding a previously deleted id cancels its tombstone.
    setRemoved((current) => current.filter((id) => id !== button.id))
    setDraft(null)
    setEditingIndex(null)
    setError(null)
  }

  const remove = (index: number) => {
    const button = buttons[index]
    setButtons(buttons.filter((_, i) => i !== index))
    // Only an inherited button needs a tombstone; a brand new one is simply gone.
    if (loaded.some((b) => b.id === button.id)) {
      setRemoved((current) => (current.includes(button.id) ? current : [...current, button.id]))
    }
    if (editingIndex === index) {
      setDraft(null)
      setEditingIndex(null)
    }
  }

  const move = (index: number, delta: number) => {
    const target = index + delta
    if (target < 0 || target >= buttons.length) return
    const next = [...buttons]
    ;[next[index], next[target]] = [next[target], next[index]]
    setButtons(next)
  }

  const sections = Array.from(new Set(buttons.map((b) => b.section || 'General')))

  return (
    <div>
      <PageHeader
        title="Menu editor"
        description="Every WhatsApp menu option, editable. A button can require a feature flag (hidden when that capability is off), start a flow, route to an intent, or appear only out of hours."
        actions={
          <>
            <Button size="sm" variant="secondary" icon={<ListPlus className="h-4 w-4" />} onClick={startAdd}>
              Add option
            </Button>
            <Button size="sm" variant="secondary" loading={action.busy} icon={<Save className="h-4 w-4" />} onClick={() => commit(false)}>
              Save draft
            </Button>
            <Button size="sm" variant="primary" loading={action.busy} icon={<Send className="h-4 w-4" />} onClick={() => commit(true)}>
              {isSuperAdmin ? 'Save & publish' : 'Submit for approval'}
            </Button>
          </>
        }
        meta={
          <>
            <Badge tone="accent">{vertical.short}</Badge>
            <Badge tone="neutral">{buttons.length} options in the editor</Badge>
            {detail.data?.has_draft && <Badge tone="warning">draft in progress</Badge>}
            {removed.length > 0 && <Badge tone="danger">{removed.length} marked for deletion</Badge>}
            <Badge tone="muted">live v{detail.data?.current_version ?? 0}</Badge>
          </>
        }
      />

      {action.error && (
        <Alert tone="danger" title="Action failed" className="mb-4">
          {action.error}
        </Alert>
      )}
      {error && (
        <Alert tone="warning" title="Fix this first" className="mb-4">
          {error}
        </Alert>
      )}
      {uncleared.length > 0 && (
        <Alert tone="warning" title="Inherited values that will not clear" className="mb-4">
          <ul className="list-disc space-y-1 pl-4">
            {uncleared.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
          <p className="mt-2">
            A layer never blanks out a lower layer with an empty value, so removing an inherited flag, flow or
            intent needs a backend change. Everything else you set will apply.
          </p>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader title="Menu text" description="What the customer sees above the options." />
          <CardBody className="space-y-4">
            <Input
              label="Header"
              value={menu.header}
              onChange={(e) => setMenu({ ...menu, header: e.target.value })}
              placeholder="Leeway Softech"
            />
            <Textarea
              label="Body"
              value={menu.body}
              onChange={(e) => setMenu({ ...menu, body: e.target.value })}
              rows={3}
            />
            <Input
              label="Footer"
              value={menu.footer}
              onChange={(e) => setMenu({ ...menu, footer: e.target.value })}
            />
            <Input
              label="Button text"
              value={menu.button_text}
              onChange={(e) => setMenu({ ...menu, button_text: e.target.value })}
            />
          </CardBody>
        </Card>

        <div className="space-y-4 lg:col-span-2">
          {draft && (
            <Card>
              <CardHeader
                title={editingIndex === -1 ? 'New menu option' : `Edit "${buttons[editingIndex ?? 0]?.title}"`}
                description="The id is what the flow runner and routing dispatcher switch on — keep it stable."
                actions={
                  <Button size="sm" variant="ghost" onClick={() => { setDraft(null); setEditingIndex(null) }} icon={<X className="h-4 w-4" />} />
                }
              />
              <CardBody className="space-y-4">
                <div className="grid gap-4 sm:grid-cols-2">
                  <Input
                    label="Id"
                    value={draft.id}
                    onChange={(e) => setDraft({ ...draft, id: e.target.value })}
                    placeholder="menu_quote"
                    hint="Lowercase, no spaces. Referenced by intents and flows."
                  />
                  <Input
                    label="Title"
                    value={draft.title}
                    onChange={(e) => {
                      const title = e.target.value
                      setDraft({ ...draft, title })
                      if (draft.intent === NEW_INTENT && !newNameTouched) {
                        setNewIntentName(slugify(title))
                      }
                    }}
                    placeholder="Get a Quote"
                  />
                  <div className="space-y-3">
                    <Select
                      label="Add to section"
                      value={sections.includes(draft.section) ? draft.section : '__new_section__'}
                      onChange={(e) => {
                        const value = e.target.value
                        if (value === '__new_section__') {
                          setDraft({ ...draft, section: sections.includes(draft.section) ? '' : draft.section })
                        } else {
                          setDraft({ ...draft, section: value })
                        }
                      }}
                      hint="Pick an existing section or add a new section."
                    >
                      {sections.map((section) => (
                        <option key={section} value={section}>{section}</option>
                      ))}
                      <option value="__new_section__">+ New section</option>
                    </Select>
                    {(!sections.length || !sections.includes(draft.section)) && (
                      <Input
                        label="New section name"
                        value={draft.section}
                        onChange={(e) => setDraft({ ...draft, section: e.target.value })}
                        placeholder="🛠️ Services"
                      />
                    )}
                  </div>
                  <Input
                    label="Icon"
                    value={draft.icon}
                    onChange={(e) => setDraft({ ...draft, icon: e.target.value })}
                    placeholder="🛠️"
                    hint="An emoji. Shown in section headers."
                  />
                </div>
                <Textarea
                  label="Description"
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  rows={2}
                />
                <Switch
                  checked={draft.enabled}
                  onChange={(enabled) => setDraft({ ...draft, enabled })}
                  label="Menu option enabled"
                  description="When off, this option is hidden from customers. Service feature permissions remain unchanged."
                />
                <div className="grid gap-4 sm:grid-cols-3">
                  <Select
                    label="Requires feature"
                    value={draft.requires_feature ?? ''}
                    onChange={(e) => setDraft({ ...draft, requires_feature: e.target.value || null })}
                    hint="Hidden when the capability is off."
                  >
                    <option value="">Always show</option>
                    {FEATURE_FLAGS.map((flag) => (
                      <option key={flag} value={flag}>
                        {FEATURE_LABELS[flag].label}
                      </option>
                    ))}
                  </Select>
                  <Select
                    label="Starts flow"
                    value={draft.flow ?? ''}
                    onChange={(e) => setDraft({ ...draft, flow: e.target.value || null })}
                  >
                    <option value="">No flow</option>
                    {flowNames.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </Select>
                  <Select
                    label="Routes to intent"
                    value={draft.intent ?? ''}
                    onChange={(e) => {
                      const value = e.target.value
                      if (value === NEW_INTENT) {
                        setDraft({ ...draft, intent: NEW_INTENT })
                        setNewNameTouched(false)
                        if (!newIntentName.trim()) setNewIntentName(slugify(draft.title))
                      } else {
                        setDraft({ ...draft, intent: value || null })
                      }
                    }}
                    hint="When tapped, the bot replies with the page's answer."
                  >
                    <option value="">No intent</option>
                    {intentOptions.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                    <option value={NEW_INTENT}>+ New page — write its answer…</option>
                  </Select>
                </div>

                {draft.intent && (
                  <div className="space-y-4 rounded-lg bg-surface-panel p-4 ring-1 ring-inset ring-surface-line">
                    {draft.intent === NEW_INTENT ? (
                      <Input
                        label="New page id"
                        value={newIntentName}
                        onChange={(e) => {
                          setNewNameTouched(true)
                          setNewIntentName(e.target.value)
                        }}
                        placeholder="why_choose_us"
                        hint="Auto-filled from the title. Lowercase snake_case — this becomes the intent the bot routes to."
                      />
                    ) : null}
                    {(() => {
                      const key = draft.intent === NEW_INTENT ? newIntentName.trim() : draft.intent
                      const existingIntent = intentMap.get(key)
                      const edit = intentEdits[key]
                      const answer = edit?.answer ?? existingIntent?.answer ?? ''
                      const keywords = edit?.keywords ?? [...(existingIntent?.keywords ?? [])]
                      const setEdit = (patch: Partial<IntentEdit>) => {
                        const base: IntentEdit = edit ?? {
                          answer,
                          keywords: [...keywords],
                        }
                        setIntentEdits((prev) => ({ ...prev, [key]: { ...base, ...patch } }))
                      }
                      return (
                        <>
                          <Textarea
                            label={draft.intent === NEW_INTENT ? 'Answer text' : `Answer text — ${key}`}
                            rows={5}
                            value={answer}
                            onChange={(e) => setEdit({ answer: e.target.value })}
                            hint='What the bot replies when this option is tapped, or a typed question matches. "• " starts a bullet, *stars* make a word bold. Leave empty and questions fall through to the knowledge base.'
                          />
                          <div>
                            <TagInput
                              value={keywords}
                              onChange={(next) => setEdit({ keywords: next })}
                              placeholder="Add a keyword and press Enter"
                            />
                            <p className="hint">
                              Phrases that route a typed question to this answer. Editing a
                              built-in page (technologies, careers…) needs its own permission.
                            </p>
                          </div>
                        </>
                      )
                    })()}
                  </div>
                )}
                <Switch
                  checked={draft.out_of_hours_only}
                  onChange={(out_of_hours_only) => setDraft({ ...draft, out_of_hours_only })}
                  label="Show only out of hours"
                  description="Useful for a 'request a callback' option that is hidden while the team is online."
                />
                <div className="flex justify-end gap-2">
                  <Button variant="ghost" onClick={() => { setDraft(null); setEditingIndex(null) }}>
                    Cancel
                  </Button>
                  <Button variant="primary" onClick={saveDraftButton}>
                    {editingIndex === -1 ? 'Add option' : 'Save changes'}
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}

          {!buttons.length && !draft ? (
            <Card>
              <EmptyState
                title="No menu options yet"
                description="This tenant currently sends a plain text menu. Add the first option, or publish a version to inherit the field defaults."
                action={
                  <Button variant="primary" onClick={startAdd} icon={<ListPlus className="h-4 w-4" />}>
                    Add the first option
                  </Button>
                }
              />
            </Card>
          ) : (
            sections.map((section) => (
              <Card key={section}>
                <CardHeader
                  title={section}
                  description={`${buttons.filter((b) => (b.section || 'General') === section).length} option(s)`}
                />
                <CardBody className="space-y-2">
                  {buttons
                    .map((button, index) => ({ button, index }))
                    .filter(({ button }) => (button.section || 'General') === section)
                    .map(({ button, index }) => {
                      const gated =
                        button.requires_feature && !effective.features?.[button.requires_feature as FeatureFlag]
                      return (
                        <div key={button.id} className="rounded-lg bg-surface-panel p-3 ring-1 ring-inset ring-surface-line">
                          <div className="flex flex-wrap items-start gap-3">
                            <div className="min-w-0 flex-1">
                              <div className="flex flex-wrap items-center gap-2">
                                {button.icon && <span className="text-sm">{button.icon}</span>}
                                <span className="text-sm font-medium text-slate-100">{button.title}</span>
                                <code className="rounded bg-surface-raised px-1.5 py-0.5 font-mono text-xs text-slate-500 ring-1 ring-surface-line">
                                  {button.id}
                                </code>
                                {button.flow && <Badge tone="accent">flow: {button.flow}</Badge>}
                                {button.intent && <Badge tone="neutral">intent: {button.intent}</Badge>}
                                {button.out_of_hours_only && <Badge tone="warning">out of hours only</Badge>}
                                {!button.enabled && <Badge tone="muted">disabled</Badge>}
                                {button.requires_feature && (
                                  <Badge tone={gated ? 'danger' : 'muted'}>
                                    needs {FEATURE_LABELS[button.requires_feature as FeatureFlag]?.label}
                                  </Badge>
                                )}
                              </div>
                              {button.description && (
                                <p className="mt-1 text-xs leading-relaxed text-slate-500">{button.description}</p>
                              )}
                            </div>
                            <div className="flex shrink-0 items-center gap-1.5">
                              <Button size="sm" variant="ghost" onClick={() => move(index, -1)} title="Move up" icon={<ArrowUp className="h-4 w-4" />} />
                              <Button size="sm" variant="ghost" onClick={() => move(index, 1)} title="Move down" icon={<ArrowDown className="h-4 w-4" />} />
                              <Button size="sm" variant="secondary" onClick={() => startEdit(index)} icon={<Pencil className="h-4 w-4" />}>
                                Edit
                              </Button>
                              <Button
                                size="sm"
                                variant="ghost"
                                title={loaded.some((b) => b.id === button.id) ? 'Delete this option' : 'Remove this option'}
                                icon={<Trash2 className="h-4 w-4" />}
                                onClick={() => remove(index)}
                              />
                            </div>
                          </div>
                        </div>
                      )
                    })}
                </CardBody>
              </Card>
            ))
          )}

          {buttons.length > 0 && (
            <Card>
              <CardBody>
                <SectionTitle hint="The bot only sees the published version. Save a draft as often as you like — nothing changes until you publish.">
                  Publishing
                </SectionTitle>
                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" loading={action.busy} icon={<Save className="h-4 w-4" />} onClick={() => commit(false)}>
                    Save draft
                  </Button>
                  <Button variant="primary" loading={action.busy} icon={<Send className="h-4 w-4" />} onClick={() => commit(true)}>
                    {isSuperAdmin ? 'Save & publish' : 'Submit for approval'}
                  </Button>
                </div>
              </CardBody>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

/** `effective.menu` is a partial layer on the wire; fill the gaps the schema defaults. */
function normaliseMenu(menu: NonNullable<ProfileSnapshot['menu']>): MenuSpec {
  return {
    key: menu.key ?? 'kb_main',
    header: menu.header ?? '',
    body: menu.body ?? 'What would you like help with?',
    footer: menu.footer ?? '',
    button_text: menu.button_text ?? 'Show Options',
    buttons: (menu.buttons ?? []).map((button) => ({
      ...blankButton(0),
      ...button,
    })) as MenuButton[],
  }
}

function validateButton(button: ButtonDraft, others: ButtonDraft[]): string | null {
  if (!button.id.trim()) return 'Every menu option needs an id.'
  if (!/^[a-z0-9_]+$/.test(button.id.trim())) return 'Ids must be lowercase letters, digits and underscores.'
  if (others.some((o) => o.id === button.id)) return `The id "${button.id}" is already used by another option.`
  if (!button.title.trim()) return 'Every menu option needs a title.'
  if (button.intent === NEW_INTENT) return 'Finish the new page first — give it an id, then save the option.'
  return null
}

function validate(menu: MenuSpec, buttons: ButtonDraft[]): string | null {
  if (!menu.body.trim()) return 'The menu needs a body — it is what the customer reads first.'
  for (let i = 0; i < buttons.length; i += 1) {
    const problem = validateButton(buttons[i], buttons.filter((_, j) => j !== i))
    if (problem) return problem
  }
  return null
}
