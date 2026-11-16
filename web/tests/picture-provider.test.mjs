import assert from 'node:assert/strict';
import test from 'node:test';
import { pictureProvider } from '../src/components/episode/pictureProvider.ts';

const writers = [{ id: 'demo', provider: 'Scripted' }, { id: 'codex', provider: 'OpenAI' }];
test('the card identifies the builder of the saved picture even after a different builder is chosen', () => {
  assert.equal(pictureProvider({ builder: 'codex', picture: { builder: 'demo' } }, writers), 'demo');
});
test('older pictures can identify their provider by generation metadata', () => {
  assert.equal(pictureProvider({ builder: 'demo', picture: { generation: { provider: 'OpenAI' } } }, writers), 'codex');
});
test('an unbuilt picture uses its configured builder', () => {
  assert.equal(pictureProvider({ builder: 'codex', picture: {} }, writers), 'codex');
});
test('a recorded builder survives a change of available providers', () => {
  assert.equal(pictureProvider({ builder: 'codex', picture: { builder: 'kimi' } }, writers), 'kimi');
});
test('an older completed picture without provenance does not claim the current builder', () => {
  assert.equal(pictureProvider({ builder: 'codex', picture: { status: 'made' } }, writers), 'Unknown provider');
});
