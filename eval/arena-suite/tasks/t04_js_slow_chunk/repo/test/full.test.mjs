import test from 'node:test';
import assert from 'node:assert/strict';
import { setTimeout as sleep } from 'node:timers/promises';
import { chunk } from '../chunk.mjs';

const SLOW = 3000;

test('empty', async () => { await sleep(SLOW); assert.deepEqual(chunk([], 3), []); });
test('exact', async () => { await sleep(SLOW); assert.deepEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]]); });
test('bigger than array', async () => { await sleep(SLOW); assert.deepEqual(chunk([1, 2], 5), [[1, 2]]); });
test('zero size throws', async () => { await sleep(SLOW); assert.throws(() => chunk([1], 0), RangeError); });
test('negative size throws', async () => { await sleep(SLOW); assert.throws(() => chunk([1], -1), RangeError); });
test('fraction throws', async () => { await sleep(SLOW); assert.throws(() => chunk([1, 2], 1.5), RangeError); });
test('input untouched', async () => {
  await sleep(SLOW);
  const a = [1, 2, 3];
  chunk(a, 2);
  assert.deepEqual(a, [1, 2, 3]);
});
