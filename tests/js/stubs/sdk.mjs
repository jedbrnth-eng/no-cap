// The slice of @hermes/plugin-sdk that desktop/plugin.js imports, recorded for assertions.
export const TRANSCRIPT_DIRECTIVE_AREA = 'transcript.directives'
export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const PALETTE_AREA = 'palette'
export const calls = { submitted: [], notified: [] }
const atom = v => ({ get: () => v, set: n => { v = n }, subscribe: () => () => {} })
export const host = {
  state: { focusedStoredSessionId: atom('s1'), profile: atom('default') },
  composer: { submit: (sid, text) => { calls.submitted.push([sid, text]); return true } },
  notify: n => calls.notified.push(n)
}
export function useValue(a) {
  return a.get()
}
const tag = name => props => ({ type: name, props: props || {} })
export const Popover = tag('Popover')
export const PopoverTrigger = tag('PopoverTrigger')
export const PopoverContent = tag('PopoverContent')
