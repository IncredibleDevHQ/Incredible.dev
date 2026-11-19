import assert from 'node:assert/strict';
import test from 'node:test';
import { effortName, madeOn, modelChoices, optionLabel, pickLabel } from '../src/components/episode/models.ts';

const kimi = [
  { id: '', name: 'CLI default', efforts: ['low', 'high', 'max'], default_effort: 'high', resolves: 'K3.1 Pro' },
  { id: 'kimi-code/k3.1-pro', name: 'K3.1 Pro', efforts: ['low', 'high', 'max'], default_effort: 'high' },
  { id: 'kimi-code/k3', name: 'K3', efforts: ['low', 'high', 'max'], default_effort: 'high' },
  { id: 'kimi-code/fast', name: 'K2.7 Code Highspeed', efforts: [] },
];
const claude = [
  { id: '', name: 'CLI default', efforts: ['low', 'medium', 'high', 'xhigh', 'max'] },
  { id: 'claude-fable-5-2', name: 'Fable 5.2', efforts: ['low', 'medium', 'high', 'xhigh', 'max'] },
];
const builtin = [{ id: '', name: 'claude-opus-5-5', efforts: ['low', 'high'] }];

test('an effort is said as a person reads it', () => {
  assert.equal(effortName('xhigh'), 'Extra high');
  assert.equal(effortName('max'), 'Max');
  assert.equal(effortName('careful'), 'Careful');
  assert.equal(effortName(''), '');
});

test("the first model is the agent's own default, named where the agent says which it is", () => {
  assert.equal(optionLabel(kimi[0]), 'Default · K3.1 Pro');
  assert.equal(optionLabel(claude[0]), "Agent's default");
  assert.equal(optionLabel(builtin[0]), 'claude-opus-5-5');
  assert.equal(optionLabel(kimi[2]), 'K3');
});

test('a pick is said as its model and its effort, the default effort where the agent tells', () => {
  assert.equal(pickLabel(kimi, { model: 'kimi-code/k3', effort: 'low' }), 'K3 · Low');
  assert.equal(pickLabel(kimi, { model: 'kimi-code/k3', effort: '' }), 'K3 · High');
  assert.equal(pickLabel(kimi, { model: '', effort: '' }), 'K3.1 Pro · High');
  assert.equal(pickLabel(kimi, { model: 'kimi-code/fast', effort: '' }), 'K2.7 Code Highspeed');
  assert.equal(pickLabel(claude, { model: 'claude-fable-5-2', effort: 'xhigh' }), 'Fable 5.2 · Extra high');
  assert.equal(pickLabel(claude, { model: '', effort: 'low' }), 'Low');
  // nothing picked, and the agent does not say what its default is: nothing to say
  assert.equal(pickLabel(claude, { model: '', effort: '' }), '');
  assert.equal(pickLabel(builtin, { model: '', effort: '' }), 'claude-opus-5-5');
  // a pick the agent no longer lists is still named as it was saved
  assert.equal(pickLabel(kimi, { model: 'kimi-code/gone', effort: '' }), 'kimi-code/gone');
  assert.equal(pickLabel(undefined, { model: '', effort: '' }), '');
});

test('the model list shows the default once and keeps a saved explicit pick switchable', () => {
  const explicit = 'kimi-code/k3.1-pro';
  assert.deepEqual(modelChoices(kimi, '').map(row => row.value), ['', 'kimi-code/k3', 'kimi-code/fast']);
  assert.deepEqual(modelChoices(kimi, explicit).slice(0, 2), [
    { value: '', label: 'Use default' },
    { value: explicit, label: 'K3.1 Pro' },
  ]);
  assert.deepEqual(modelChoices(kimi, '', { model: 'kimi-code/k3', effort: 'low' }), [
    { value: '', label: "Film's choice · K3 · Low" },
    { value: explicit, label: 'K3.1 Pro' },
    { value: 'kimi-code/fast', label: 'K2.7 Code Highspeed' },
  ]);
  assert.equal(modelChoices(claude, '').length, claude.length);
});

test('a made picture says the model and effort its record names, and nothing it does not know', () => {
  assert.equal(madeOn({ provider: 'Kimi Code', model: 'K3', effort: 'low' }), 'K3 · Low');
  assert.equal(madeOn({ provider: 'Anthropic', model: 'Opus 5.5', effort: 'CLI default' }), 'Opus 5.5');
  assert.equal(madeOn({ provider: 'Kimi Code', model: 'CLI default', effort: 'CLI default' }), '');
  assert.equal(madeOn({ provider: 'Scripted', model: 'demo', effort: 'Not applicable' }), 'Scripted');
  assert.equal(madeOn(null), '');
});
