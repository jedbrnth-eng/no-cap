// No Cap: the Hermes Desktop half. Receipt chips inside the assistant message and a Receipts popover in the
// status bar. Public SDK only: TRANSCRIPT_DIRECTIVE_AREA, STATUSBAR_AREAS, ctx.rest to this plugin's own backend
// (dashboard/plugin_api.py), host.composer.submit. No app DOM, no network beyond the local backend.
//
// The Python half appends `::nocap{v="2" n="<chip id>" s="<hmac>" d="<base64 json>"}` as its own paragraph, and only
// for platform "desktop" while this half is loaded (it says hello below). Attributes are untrusted text. This half
// holds no key: a chip is drawn only after the plugin's own backend (POST /verify) confirms it issued that chip for
// the chat it sits in (the host's `sessionId`). The Python half also strips every `::nocap` the model writes, on
// every surface, so a copied or invented directive gets a warning, never a fake 🧾.
import { host, Popover, PopoverContent, PopoverTrigger, STATUSBAR_AREAS, TRANSCRIPT_DIRECTIVE_AREA, useValue } from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ID = 'no-cap'
const HELLO_EVERY_MS = 10 * 60 * 1000
const MAX_D = 4096
const MAX_TEXT = 400

export const CHIP_VERDICTS = {
  CAP: { emoji: '🧢', label: 'CAP', tone: 'var(--ui-red)' },
  NO_RECEIPT: { emoji: '🤔', label: 'NO RECEIPT', tone: 'var(--ui-yellow)' },
  NO_CAP: { emoji: '🧾', label: 'NO CAP', tone: 'var(--ui-green)' }
}

// ---- pure helpers (unit-tested) --------------------------------------------------------------------------------

/** `key="value"` pairs of a directive source, the way the host parses them (tests and diagnostics only). */
export function parseDirectiveAttrs(source) {
  const out = {}
  for (const m of String(source || '').matchAll(/([a-z][\w-]{0,63})=(?:"([^"]*)"|'([^']*)')/gi)) {
    out[m[1].toLowerCase()] = m[2] ?? m[3] ?? ''
  }
  return out
}

function str(v, n = MAX_TEXT) {
  return typeof v === 'string' ? v.slice(0, n) : undefined
}

function int(v) {
  return Number.isInteger(v) ? v : undefined
}

function cleanChip(raw) {
  if (!raw || typeof raw !== 'object' || !(raw.v in CHIP_VERDICTS)) return null
  // Claims are the model's markdown: drop inline-code backticks so a chip reads `auth.py` as auth.py.
  const chip = { v: raw.v, t: (str(raw.t) ?? '').replace(/`/g, '') }
  for (const k of ['k', 'o', 'x', 'q', 'w', 'r']) {
    const s = str(raw[k])
    if (s) chip[k] = s
  }
  for (const k of ['n', 'e']) {
    const i = int(raw[k])
    if (i !== undefined) chip[k] = i
  }
  return chip
}

/** Decode the `d` attribute: base64 of UTF-8 JSON `{ c: [chip…], more }`. Null on anything malformed. */
export function decodePayload(d) {
  if (typeof d !== 'string' || !d || d.length > MAX_D || !/^[A-Za-z0-9+/=]+$/.test(d)) return null
  let data
  try {
    const bin = atob(d)
    const bytes = Uint8Array.from(bin, ch => ch.charCodeAt(0))
    data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  } catch {
    return null
  }
  if (!data || typeof data !== 'object' || Array.isArray(data) || !Array.isArray(data.c)) return null
  const chips = data.c.slice(0, 24).map(cleanChip).filter(Boolean)
  return { chips, more: Math.max(0, int(data.more) ?? 0), turn: str(data.t, 40) }
}

/** The well-formed attributes of a v2 directive, or null. */
export function chipAttrs(attrs) {
  const a = attrs || {}
  if (a.v !== '2') return null
  if (typeof a.n !== 'string' || !/^[0-9a-f]{32}$/.test(a.n)) return null
  if (typeof a.s !== 'string' || !/^[0-9a-f]{32}$/.test(a.s)) return null
  if (typeof a.d !== 'string' || !a.d || a.d.length > MAX_D) return null
  return { n: a.n, s: a.s, d: a.d }
}

/**
 * Ask the plugin's backend whether it issued this chip for `sessionId` (the chat the directive is rendered in).
 * 'ok' only when the backend says so for that exact session; 'bad' when it says no; 'nokey' when it can't answer.
 */
export async function verifyChip(rest, sessionId, attrs) {
  const a = chipAttrs(attrs)
  if (!a) return 'bad'
  if (typeof sessionId !== 'string' || !sessionId) return 'checking'
  try {
    const res = await rest('/verify', { body: { d: a.d, n: a.n, s: a.s, session_id: sessionId }, method: 'POST' })
    if (!res || typeof res !== 'object') return 'nokey'
    return res.ok === true && res.session_id === sessionId ? 'ok' : 'bad'
  } catch {
    return 'nokey'
  }
}

/** The expanded chip: [label, value] rows. */
export function detailRows(chip) {
  const rows = [['Claim', `“${chip.t}”`]]
  if (chip.n !== undefined) {
    const parts = [`call ${chip.n}`]
    if (chip.o) parts.push(chip.o)
    if (chip.x) parts.push(chip.x)
    if (chip.e !== undefined) parts.push(`exit ${chip.e}`)
    rows.push(['Receipt', parts.join(' · ')])
  } else {
    rows.push(['Receipt', 'no tool call this turn backs it'])
  }
  if (chip.q) rows.push([chip.v === 'CAP' ? 'Output says' : 'Output', `“${chip.q}”`])
  if (chip.w) rows.push(['Why', chip.w])
  if (chip.r) rows.push(['Re-checked', chip.r])
  return rows
}

export function summary(counts) {
  const c = counts || {}
  const parts = [`🧾 ${c.NO_CAP || 0}`]
  if (c.CAP) parts.push(`🧢 ${c.CAP}`)
  if (c.NO_RECEIPT) parts.push(`🤔 ${c.NO_RECEIPT}`)
  return parts.join(' · ')
}

// ---- views (pure: state comes in as props) ----------------------------------------------------------------------

const S = {
  wrap: { display: 'flex', flexDirection: 'column', gap: 6, margin: '4px 0 2px' },
  row: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' },
  chip: tone => ({
    alignItems: 'center',
    background: `color-mix(in srgb, ${tone} 12%, transparent)`,
    border: `1px solid color-mix(in srgb, ${tone} 45%, transparent)`,
    borderRadius: 999,
    color: 'var(--ui-text-primary)',
    cursor: 'pointer',
    display: 'inline-flex',
    font: 'inherit',
    fontSize: '0.8125rem',
    gap: 6,
    lineHeight: 1.3,
    maxWidth: '100%',
    padding: '2px 10px 2px 8px'
  }),
  tag: tone => ({ color: tone, fontSize: '0.6875rem', fontWeight: 600, letterSpacing: '0.02em', whiteSpace: 'nowrap' }),
  claim: { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: 320 },
  detail: tone => ({
    background: 'var(--ui-bg-elevated)',
    border: '1px solid var(--ui-stroke-secondary)',
    borderLeft: `3px solid ${tone}`,
    borderRadius: 8,
    display: 'grid',
    fontSize: '0.8125rem',
    gap: '4px 12px',
    gridTemplateColumns: 'max-content 1fr',
    padding: '8px 12px'
  }),
  label: { color: 'var(--ui-text-tertiary)' },
  value: { color: 'var(--ui-text-primary)', overflowWrap: 'anywhere' },
  code: {
    background: 'var(--ui-inline-code-background)',
    borderRadius: 4,
    color: 'var(--ui-inline-code-foreground)',
    fontFamily: 'var(--font-mono, ui-monospace, monospace)',
    fontSize: '0.75rem',
    padding: '0 4px'
  },
  ghost: {
    background: 'transparent',
    border: '1px solid var(--ui-stroke-secondary)',
    borderRadius: 999,
    color: 'var(--ui-text-secondary)',
    cursor: 'pointer',
    font: 'inherit',
    fontSize: '0.75rem',
    padding: '2px 10px'
  },
  muted: { color: 'var(--ui-text-tertiary)', fontSize: '0.75rem' },
  note: { color: 'var(--ui-text-tertiary)', fontSize: '0.8125rem', fontStyle: 'italic' }
}

function receiptValue(chip, label, value) {
  if (label !== 'Receipt' || !chip.x) return value
  const [head, ...rest] = value.split(` · ${chip.x}`)
  return jsxs('span', { children: [head, ' · ', jsx('code', { style: S.code, children: chip.x }), rest.join('')] })
}

function Detail({ chip }) {
  const tone = CHIP_VERDICTS[chip.v].tone
  return jsx('div', {
    role: 'region',
    style: S.detail(tone),
    children: detailRows(chip).flatMap(([label, value]) => [
      jsx('span', { style: S.label, children: label }, `${label}-l`),
      jsx('span', { style: S.value, children: receiptValue(chip, label, value) }, `${label}-v`)
    ])
  })
}

function Chip({ chip, index, open, onToggle, key }) {
  const meta = CHIP_VERDICTS[chip.v]
  return jsxs('button', {
    'aria-expanded': open,
    'data-nocap-chip': chip.v,
    onClick: () => onToggle(index),
    style: S.chip(meta.tone),
    title: open ? 'Hide the receipt' : 'Show the receipt',
    type: 'button',
    children: [
      jsx('span', { 'aria-hidden': true, children: meta.emoji }),
      jsx('span', { style: S.tag(meta.tone), children: meta.label }),
      jsx('span', { style: S.claim, children: chip.t })
    ]
  }, key)
}

/** The chips for one reply. `status`: 'checking' | 'ok' | 'bad' | 'nokey'. `open`: index of the expanded chip. */
export function ReceiptChipsView({ status, data, open, onToggle, onCap }) {
  if (!data) return null
  if (status === 'bad') {
    return jsx('div', { style: S.note, children: "⚠️ No Cap didn't issue these receipts for this chat, so they aren't shown." })
  }
  if (status === 'nokey') {
    return jsx('div', { style: S.note, children: "No Cap can't verify these receipts right now (its backend didn't answer). The text receipts above still hold. /nocap all lists them." })
  }
  if (status !== 'ok') {
    return jsx('div', { style: S.muted, children: 'checking receipts…' })
  }
  const unproven = data.chips.some(c => c.v !== 'NO_CAP')
  const tail = []
  if (data.more) tail.push(jsx('span', { style: S.muted, children: `+${data.more} more · /nocap all` }, 'more'))
  if (unproven) {
    tail.push(jsx('button', {
      'data-nocap-cap': '',
      onClick: onCap,
      style: S.ghost,
      title: 'Make the agent show receipts or take it back',
      type: 'button',
      children: '🧢 Call /cap'
    }, 'cap'))
  }
  return jsxs('div', {
    'data-nocap-receipts': '',
    style: S.wrap,
    children: [
      jsxs('div', {
        style: S.row,
        children: [
          ...data.chips.map((chip, i) => Chip({ chip, index: i, key: `c${i}`, onToggle, open: open === i })),
          ...tail
        ]
      }),
      open >= 0 && data.chips[open] ? jsx(Detail, { chip: data.chips[open] }, 'detail') : null
    ]
  })
}

/** The Receipts popover: this chat's checked replies, newest first. `open`: "<reply>:<chip>" of the expanded chip. */
export function SessionReceiptsView({ view, open, onToggle }) {
  const v = view || {}
  const replies = Array.isArray(v.replies) ? v.replies : []
  const head = jsxs('div', {
    style: { display: 'flex', flexDirection: 'column', gap: 2, marginBottom: 8 },
    children: [
      jsx('div', { style: { fontWeight: 600 }, children: 'Receipts · this chat' }),
      jsx('div', { style: S.muted, children: summary(v.counts) }),
      replies.length
        ? jsx('div', { style: S.muted, children: v.streak ? `🔥 ${v.streak} no cap in a row` : 'streak 0 (only all-🧾 replies count)' })
        : null,
      v.unsure ? jsx('div', { style: S.muted, children: `🤫 ${v.unsure} unsure claim(s) not stamped · /nocap all` }) : null
    ]
  })
  if (!replies.length) {
    return jsxs('div', { children: [head, jsx('div', { style: S.note, children: 'No checked claims in this chat yet.' })] })
  }
  return jsxs('div', {
    children: [
      head,
      ...replies.map((rep, r) => {
        const chips = (rep.c || []).map(cleanChip).filter(Boolean)
        const openChip = chips.findIndex((_, i) => open === `${r}:${i}`)
        const when = typeof rep.ts === 'number' ? new Date(rep.ts * 1000).toLocaleTimeString() : ''
        return jsxs('div', {
          style: { borderTop: '1px solid var(--ui-stroke-tertiary)', display: 'flex', flexDirection: 'column', gap: 6, padding: '8px 0' },
          children: [
            jsx('div', { style: S.muted, children: [when, rep.model, rep.calls != null ? `${rep.calls} tool call(s)` : ''].filter(Boolean).join(' · ') }),
            jsx('div', {
              style: S.row,
              children: chips.map((chip, i) => Chip({ chip, index: `${r}:${i}`, key: `c${i}`, onToggle, open: open === `${r}:${i}` }))
            }),
            openChip >= 0 ? jsx(Detail, { chip: chips[openChip] }, 'detail') : null
          ]
        }, `r${r}`)
      })
    ]
  })
}

// ---- wiring -----------------------------------------------------------------------------------------------------

export default {
  id: ID,
  name: 'No Cap',
  register(ctx) {
    const listeners = new Set()
    const verdicts = new Map() // `${sessionId}|${n}|${s}|${d}` → Promise<status>, so a re-render never re-asks

    const hello = on => {
      let call
      try {
        call = Promise.resolve(ctx.rest('/hello', { body: { on }, method: 'POST' }))
      } catch (err) {
        call = Promise.reject(err)
      }
      return call.then(() => true).catch(() => false)
    }

    const check = (sessionId, attrs) => {
      const id = `${sessionId}|${attrs && attrs.n}|${attrs && attrs.s}|${attrs && attrs.d}`
      if (!verdicts.has(id)) {
        if (verdicts.size > 500) verdicts.clear()
        const p = verifyChip((path, opts) => ctx.rest(path, opts), sessionId, attrs)
        verdicts.set(id, p)
        p.then(s => { if (s !== 'ok' && s !== 'bad') verdicts.delete(id) }) // retry 'nokey'/'checking' next time
      }
      return verdicts.get(id)
    }

    hello(true)
    ctx.setInterval(() => {
      hello(true)
    }, HELLO_EVERY_MS)
    ctx.onDispose(() => {
      hello(false)
    })
    ctx.onEvent('plugin.no-cap.receipts.updated', () => listeners.forEach(fn => fn()))

    function ReceiptChips({ attrs, sessionId }) {
      const [status, setStatus] = useState('checking')
      const [open, setOpen] = useState(-1)
      const data = decodePayload(attrs && attrs.d)
      useEffect(() => {
        let live = true
        if (!data) return undefined
        check(sessionId, attrs).then(s => live && setStatus(s))
        return () => {
          live = false
        }
      }, [sessionId, attrs && attrs.n, attrs && attrs.d, attrs && attrs.s])
      if (!attrs || attrs.v !== '2') return null
      return ReceiptChipsView({
        data,
        onCap: () => {
          const sent = host.composer.submit(sessionId ?? null, '/cap')
          if (!sent) host.notify({ kind: 'warning', message: 'Open that chat to call /cap' })
        },
        onToggle: i => setOpen(cur => (cur === i ? -1 : i)),
        open,
        status
      })
    }

    function ReceiptsStatus() {
      const sid = useValue(host.state.focusedStoredSessionId)
      const [view, setView] = useState(null)
      const [open, setOpen] = useState('')
      const [tick, setTick] = useState(0)
      useEffect(() => {
        const bump = () => setTick(t => t + 1)
        listeners.add(bump)
        const timer = setInterval(bump, 30000)
        return () => {
          listeners.delete(bump)
          clearInterval(timer)
        }
      }, [])
      useEffect(() => {
        let live = true
        if (!sid) {
          setView(null)
          return undefined
        }
        ctx
          .rest(`/session?id=${encodeURIComponent(sid)}`)
          .then(v => live && setView(v))
          .catch(() => live && setView(null))
        return () => {
          live = false
        }
      }, [sid, tick])
      if (!view || !Array.isArray(view.replies) || !view.replies.length) return null
      return jsxs(Popover, {
        children: [
          jsx(PopoverTrigger, {
            asChild: true,
            children: jsx('button', {
              style: { background: 'transparent', border: 0, color: 'var(--ui-text-tertiary)', cursor: 'pointer', font: 'inherit', fontSize: '0.6875rem', padding: '0 6px' },
              title: 'No Cap receipts for this chat',
              type: 'button',
              children: summary(view.counts)
            })
          }),
          jsx(PopoverContent, {
            align: 'end',
            style: { fontSize: '0.8125rem', maxHeight: 420, overflowY: 'auto', width: 380 },
            children: SessionReceiptsView({ onToggle: k => setOpen(cur => (cur === k ? '' : k)), open, view })
          })
        ]
      })
    }

    ctx.register({
      area: TRANSCRIPT_DIRECTIVE_AREA,
      data: { name: 'nocap', render: props => jsx(ReceiptChips, { attrs: props.attrs, sessionId: props.sessionId }) },
      id: 'receipt-chips'
    })
    ctx.register({ area: STATUSBAR_AREAS.right, id: 'receipts', order: 140, render: () => jsx(ReceiptsStatus, {}) })
  }
}
