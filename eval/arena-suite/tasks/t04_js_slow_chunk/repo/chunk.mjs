export function chunk(arr, size) {
  if (size < 1) return [];
  const out = [];
  for (let i = 0; i + size <= arr.length; i += size) out.push(arr.slice(i, i + size));
  return out;
}
