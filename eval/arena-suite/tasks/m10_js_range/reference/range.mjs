export function range(start, end, step = 1) {
  if (step === 0) throw new RangeError('step must not be 0');
  const out = [];
  if (step > 0) for (let i = start; i < end; i += step) out.push(i);
  else for (let i = start; i > end; i += step) out.push(i);
  return out;
}
