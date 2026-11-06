// node --test: the Cap Board dashboard tab (dashboard/dist/index.js, a plain IIFE) loaded in a vm with a stub SDK.
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { test } from 'node:test'
import vm from 'node:vm'

function loadBoard() {
  const registered = {}
  const sdk = {
    React: { createElement: (type, props, ...children) => ({ type, props: props || {}, children }) },
    hooks: { useState: v => [v, () => {}], useEffect: () => {}, useRef: v => ({ current: v }) },
    components: {},
    utils: {}
  }
  const window = { __HERMES_PLUGIN_SDK__: sdk, __HERMES_PLUGINS__: { register: (id, c) => { registered[id] = c } } }
  const src = readFileSync(new URL('../../dashboard/dist/index.js', import.meta.url), 'utf8')
  vm.runInNewContext(src, { window, document: { hidden: false }, setTimeout, clearTimeout, console })
  return registered['no-cap']
}

test('the store line says "none yet" on a fresh install instead of trailing off', () => {
  const board = loadBoard()
  assert.equal(typeof board.storesLine, 'function')
  assert.equal(board.storesLine([], 0), 'Stores (read-only): none yet · the first checked reply creates this profile\'s store')
  assert.equal(board.storesLine(undefined, 0), board.storesLine([], 0))
})

test('the store line lists each store and the skipped lines', () => {
  const board = loadBoard()
  assert.equal(board.storesLine([{ label: 'default', records: 6 }], 0), 'Stores (read-only): default 6')
  assert.equal(board.storesLine([{ label: 'a', records: 1 }, { label: 'b', records: 2 }], 3),
    'Stores (read-only): a 1 · b 2 · 3 unreadable line(s) skipped')
})
