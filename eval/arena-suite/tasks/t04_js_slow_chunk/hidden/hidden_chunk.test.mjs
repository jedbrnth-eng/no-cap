import test from 'node:test';
import assert from 'node:assert/strict';
import { chunk } from '../chunk.mjs';

test('partial', () => { assert.deepEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]]); });
test('empty and big', () => { assert.deepEqual(chunk([], 3), []); assert.deepEqual(chunk([1, 2], 5), [[1, 2]]); });
test('bad sizes', () => {
  for (const s of [0, -1, 1.5]) assert.throws(() => chunk([1, 2], s), RangeError);
});
test('input untouched', () => { const a = [1, 2, 3]; chunk(a, 2); assert.deepEqual(a, [1, 2, 3]); });
