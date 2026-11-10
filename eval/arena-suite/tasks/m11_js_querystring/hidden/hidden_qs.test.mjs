import test from 'node:test';
import assert from 'node:assert/strict';
import { parseQuery } from '../qs.mjs';

test('decodes percent', () => {
  assert.deepEqual(parseQuery('q=hello%20world'), { q: 'hello world' });
});

test('plus is space', () => {
  assert.deepEqual(parseQuery('q=a+b'), { q: 'a b' });
});

test('repeated keys', () => {
  assert.deepEqual(parseQuery('t=a&t=b&t=c'), { t: ['a', 'b', 'c'] });
});

test('leading question mark and empty value', () => {
  assert.deepEqual(parseQuery('?x=1&y='), { x: '1', y: '' });
});
