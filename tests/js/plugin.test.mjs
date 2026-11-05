// node --import ./tests/js/register.mjs --test tests/js/
// The Desktop half of No Cap, run unmodified against stubbed SDK/React specifiers.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'

import { resetHooks } from 'react'
import { calls } from '@hermes/plugin-sdk'
import plugin, {
  CHIP_VERDICTS,
  decodePayload,
  detailRows,
  parseDirectiveAttrs,
  ReceiptChipsView,
  SessionReceiptsView,
  summary,
  verifySignature
} from '../../desktop/plugin.js'

const fixture = JSON.parse(readFileSync(new URL('./fixtures/directive.json', import.meta.url), 'utf8'))
const attrs = parseDirectiveAttrs(fixture.directive)

// ---- tree helpers ------------------------------------------------------------------------------------------------
function walk(node, out = []) {
  if (node == null || typeof node === 'boolean') return out
  if (Array.isArray(node)) {
    node.forEach(n => walk(n, out))
    return out
  }
  if (typeof node === 'string' || typeof node === 'number') {
    out.push({ text: String(node) })
    return out
  }
  out.push(node)
  if (typeof node.type === 'function') return walk(node.type(node.props), out) // shallow render a child component
  walk(node.props?.children, out)
  return out
}
const text = node => walk(node).filter(n => 'text' in n).map(n => n.text).join(' ')
const buttons = node => walk(node).filter(n => n.type === 'button')

// ---- decoding ----------------------------------------------------------------------------------------------------
test('decodes the directive Python emits', () => {
  assert.equal(attrs.v, '1')
  const data = decodePayload(attrs.d)
  assert.equal(data.chips.length, 4)
  assert.deepEqual(data.chips.map(c => c.v), ['CAP', 'CAP', 'NO_RECEIPT', 'NO_CAP'])
  const cap = data.chips[0]
  assert.equal(cap.t, 'All tests pass.')
  assert.equal(cap.x, 'pytest -q')
  assert.equal(cap.e, 1)
  assert.equal(cap.q, '3 failed, 41 passed in 0.52s')
  assert.equal(data.more, 0)
})

test('garbage attributes render nothing rather than a guess', () => {
  for (const bad of [undefined, '', '!!!', btoa('not json'), btoa('[]'), btoa('{"c":"x"}'), 'x'.repeat(5000)]) {
    assert.equal(decodePayload(bad), null, String(bad).slice(0, 20))
  }
})

test('unknown verdicts and wrong field types are dropped', () => {
  const raw = { c: [{ v: 'LIES', t: 'x' }, { v: 'CAP', t: 7, e: 'one', x: ['a'] }, { v: 'NO_CAP', t: 'ok', e: 0 }] }
  const d = btoa(unescape(encodeURIComponent(JSON.stringify(raw))))
  const data = decodePayload(d)
  assert.deepEqual(data.chips.map(c => c.v), ['CAP', 'NO_CAP'])
  assert.equal(data.chips[0].t, '')
  assert.equal(data.chips[0].e, undefined)
  assert.equal(data.chips[0].x, undefined)
  assert.equal(data.chips[1].e, 0)
  assert.deepEqual(Object.keys(CHIP_VERDICTS).sort(), ['CAP', 'NO_CAP', 'NO_RECEIPT'])
})

test('inline-code backticks are dropped from chip text', () => {
  const d = Buffer.from(JSON.stringify({ c: [{ v: 'NO_CAP', t: 'I fixed `auth.py`', x: 'cat `x`' }] })).toString('base64')
  const chip = decodePayload(d).chips[0]
  assert.equal(chip.t, 'I fixed auth.py')
  assert.equal(chip.x, 'cat `x`') // commands stay verbatim
})

test('unicode survives base64', () => {
  const raw = { c: [{ v: 'NO_CAP', t: 'Tests pass — “all” ✅ テスト' }] }
  const d = Buffer.from(JSON.stringify(raw), 'utf8').toString('base64')
  assert.equal(decodePayload(d).chips[0].t, 'Tests pass — “all” ✅ テスト')
})

// ---- signature ---------------------------------------------------------------------------------------------------
test('the HMAC matches the Python signer', async () => {
  assert.equal(await verifySignature(fixture.key, attrs.d, attrs.s), true)
})

test('a tampered payload, signature or key fails', async () => {
  assert.equal(await verifySignature(fixture.key, attrs.d.slice(0, -4) + 'AAAA', attrs.s), false)
  assert.equal(await verifySignature(fixture.key, attrs.d, '0'.repeat(32)), false)
  assert.equal(await verifySignature('f'.repeat(64), attrs.d, attrs.s), false)
  assert.equal(await verifySignature('', attrs.d, attrs.s), false)
  assert.equal(await verifySignature(fixture.key, attrs.d, undefined), false)
})

// ---- chips -------------------------------------------------------------------------------------------------------
const data = decodePayload(attrs.d)

test('verified chips: one button per receipt, verdict first', () => {
  const tree = ReceiptChipsView({ status: 'ok', data, open: -1, onToggle: () => {}, onCap: () => {} })
  const chips = buttons(tree).filter(b => b.props['data-nocap-chip'] !== undefined)
  assert.equal(chips.length, 4)
  assert.match(text(chips[0]), /🧢/)
  assert.match(text(chips[0]), /All tests pass\./)
  assert.match(text(chips[2]), /🤔/)
  assert.match(text(chips[3]), /🧾/)
  assert.equal(chips[0].props['aria-expanded'], false)
})

test('an open chip shows the cited command, exit code and quoted output line', () => {
  const tree = ReceiptChipsView({ status: 'ok', data, open: 0, onToggle: () => {}, onCap: () => {} })
  const t = text(tree)
  assert.match(t, /call 1/)
  assert.match(t, /terminal/)
  assert.match(t, /pytest -q/)
  assert.match(t, /exit 1/)
  assert.match(t, /3 failed, 41 passed in 0\.52s/)
  const chips = buttons(tree).filter(b => b.props['data-nocap-chip'] !== undefined)
  assert.equal(chips[0].props['aria-expanded'], true)
})

test('a claim with no receipt says why', () => {
  const rows = detailRows(data.chips[2])
  assert.deepEqual(rows.map(r => r[0]), ['Claim', 'Receipt', 'Why'])
  assert.match(rows[1][1], /no tool call/)
  assert.match(rows[2][1], /no deploy command ran/)
})

test('clicking a chip toggles it', () => {
  const toggled = []
  const tree = ReceiptChipsView({ status: 'ok', data, open: -1, onToggle: i => toggled.push(i), onCap: () => {} })
  buttons(tree).filter(b => b.props['data-nocap-chip'] !== undefined)[1].props.onClick()
  assert.deepEqual(toggled, [1])
})

test('Call cap button only when something is unproven', () => {
  const capped = []
  const tree = ReceiptChipsView({ status: 'ok', data, open: -1, onToggle: () => {}, onCap: () => capped.push(1) })
  const cap = buttons(tree).find(b => b.props['data-nocap-cap'] !== undefined)
  assert.ok(cap)
  cap.props.onClick()
  assert.deepEqual(capped, [1])
  const clean = { chips: [data.chips[3]], more: 0 }
  const t2 = ReceiptChipsView({ status: 'ok', data: clean, open: -1, onToggle: () => {}, onCap: () => {} })
  assert.equal(buttons(t2).find(b => b.props['data-nocap-cap'] !== undefined), undefined)
})

test('a bad signature draws a warning and no chips', () => {
  const tree = ReceiptChipsView({ status: 'bad', data, open: -1, onToggle: () => {}, onCap: () => {} })
  assert.equal(buttons(tree).filter(b => b.props['data-nocap-chip'] !== undefined).length, 0)
  assert.match(text(tree), /didn't issue/)
})

test('no key (backend unreachable) fails closed', () => {
  const tree = ReceiptChipsView({ status: 'nokey', data, open: -1, onToggle: () => {}, onCap: () => {} })
  assert.equal(buttons(tree).filter(b => b.props['data-nocap-chip'] !== undefined).length, 0)
  assert.match(text(tree), /can't verify/i)
})

test('more than fit is counted, with a pointer to /nocap all', () => {
  const tree = ReceiptChipsView({ status: 'ok', data: { chips: data.chips, more: 3 }, open: -1, onToggle() {}, onCap() {} })
  assert.match(text(tree), /\+3 more/)
  assert.match(text(tree), /\/nocap all/)
})

// ---- session panel -----------------------------------------------------------------------------------------------
test('summary counts', () => {
  assert.equal(summary({ CAP: 1, NO_RECEIPT: 2, NO_CAP: 3 }), '🧾 3 · 🧢 1 · 🤔 2')
  assert.equal(summary({ CAP: 0, NO_RECEIPT: 0, NO_CAP: 0 }), '🧾 0')
})

test('panel lists replies newest first with their chips', () => {
  const view = {
    session_id: 's1', counts: { CAP: 1, NO_RECEIPT: 0, NO_CAP: 1 }, unsure: 2, streak: 0, models: ['m'],
    replies: [{ ts: 2, model: 'm', calls: 2, c: [{ v: 'NO_CAP', t: 'newer', k: 'tests' }] },
      { ts: 1, model: 'm', calls: 1, c: [{ v: 'CAP', t: 'older', k: 'tests', x: 'pytest -q', e: 1, n: 1 }] }]
  }
  const t = text(SessionReceiptsView({ view, open: '', onToggle() {} }))
  assert.ok(t.indexOf('newer') < t.indexOf('older'))
  assert.match(t, /🧾 1 · 🧢 1/)
  assert.match(t, /streak reset by a 🧢|no cap in a row/)
  assert.match(t, /🤫 2 unsure claim\(s\) not stamped/)
})

test('panel empty state', () => {
  const t = text(SessionReceiptsView({ view: { replies: [], counts: { CAP: 0, NO_RECEIPT: 0, NO_CAP: 0 } }, open: '', onToggle() {} }))
  assert.match(t, /No checked claims in this chat yet/)
})

// ---- registration ------------------------------------------------------------------------------------------------
function fakeCtx(restImpl) {
  const ctx = {
    registered: [], rests: [], disposers: [], intervals: [], events: [],
    register(c) { this.registered.push(c); return () => {} },
    registerMany(cs) { cs.forEach(c => this.register(c)); return () => {} },
    rest(path, opts) { this.rests.push([path, opts]); return restImpl ? restImpl(path, opts) : Promise.resolve({ ok: true, key: fixture.key }) },
    onDispose(fn) { this.disposers.push(fn) },
    setInterval(fn, ms) { this.intervals.push(ms); return () => {} },
    setTimeout(fn) { return () => {} },
    onEvent(type, fn) { this.events.push(type); return () => {} }
  }
  return ctx
}

test('registers the nocap directive and a status-bar receipts item', () => {
  const ctx = fakeCtx()
  assert.equal(plugin.id, 'no-cap')
  plugin.register(ctx)
  const directive = ctx.registered.find(c => c.area === 'transcript.directives')
  assert.equal(directive.data.name, 'nocap')
  assert.equal(typeof directive.data.render, 'function')
  assert.ok(ctx.registered.find(c => c.area === 'statusBar.right'))
})

test('says hello on load, every 10 minutes, and goodbye on dispose', async () => {
  const ctx = fakeCtx()
  plugin.register(ctx)
  await Promise.resolve()
  assert.deepEqual(ctx.rests[0], ['/hello', { method: 'POST', body: { on: true } }])
  assert.ok(ctx.intervals.includes(10 * 60 * 1000))
  ctx.disposers.forEach(fn => fn())
  assert.deepEqual(ctx.rests.at(-1), ['/hello', { method: 'POST', body: { on: false } }])
  assert.ok(ctx.events.includes('plugin.no-cap.receipts.updated'))
})

test('the directive render is a component element with the attrs', () => {
  const ctx = fakeCtx()
  plugin.register(ctx)
  const directive = ctx.registered.find(c => c.area === 'transcript.directives')
  resetHooks()
  const el = directive.data.render({ attrs, sessionId: 's1', streaming: false, source: fixture.directive })
  assert.equal(typeof el.type, 'function')
  assert.equal(el.props.attrs, attrs)
  assert.equal(el.props.sessionId, 's1')
})

test('Call cap submits /cap to the chat that owns the card', () => {
  const ctx = fakeCtx()
  plugin.register(ctx)
  const directive = ctx.registered.find(c => c.area === 'transcript.directives')
  const el = directive.data.render({ attrs, sessionId: 's9', streaming: false, source: '' })
  resetHooks(['ok', -1])
  const tree = el.type(el.props)
  buttons(tree).find(b => b.props['data-nocap-cap'] !== undefined).props.onClick()
  assert.deepEqual(calls.submitted.at(-1), ['s9', '/cap'])
})

test('the shipped file stays inside the SDK surface (three specifiers, no eval, no app DOM)', () => {
  const src = readFileSync(new URL('../../desktop/plugin.js', import.meta.url), 'utf8')
  const specs = [...src.matchAll(/^import[^'"]*['"]([^'"]+)['"]/gm)].map(m => m[1])
  assert.deepEqual([...new Set(specs)].sort(), ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime'])
  assert.doesNotMatch(src, /\beval\(|new Function|querySelector|document\.body|innerHTML|#[0-9a-f]{3,6}\b/i)
})
