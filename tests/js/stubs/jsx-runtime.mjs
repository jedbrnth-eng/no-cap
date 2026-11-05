// Elements as plain objects: { type, props }. Tests walk the tree instead of mounting React.
export function jsx(type, props) {
  return { type, props: props || {} }
}
export const jsxs = jsx
export const Fragment = 'Fragment'
