import test from 'node:test';
import assert from 'node:assert/strict';
import { titleCase } from '../text.mjs';

test('every word', () => {
  assert.equal(titleCase('the quick fox'), 'The Quick Fox');
});

test('rest lowercase', () => {
  assert.equal(titleCase('hELLO wORLD'), 'Hello World');
});

test('empty', () => {
  assert.equal(titleCase(''), '');
});
