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

const available = [
  { id: 'demo', ready: true }, { id: 'claude', ready: false }, { id: 'codex', ready: true },
];
const catalog = {
  codex: [{id: '', name: 'CLI default'}, {id: 'gpt-example', name: 'gpt-example'}],
  claude: [{id: '', name: 'CLI default'}],
};
test('a scripted beat suggests a ready AI model and preserves its original attribution', async () => {
  const { editModel } = await import('../src/components/episode/pictureProvider.ts');
  const unit = {builder: 'demo', builder_pick: null, picture: {builder: 'demo'}, model_pick: {}};
  assert.deepEqual(editModel(unit, available, catalog), {writer: 'codex', model: 'gpt-example', suggested: true});
  assert.equal(pictureProvider(unit, available), 'demo');
  assert.equal(editModel(unit, available.filter(w => w.id !== 'codex'), catalog).writer, null);
});
test('saved models and explicit local preview take priority over a suggestion', async () => {
  const { editModel } = await import('../src/components/episode/pictureProvider.ts');
  const unit = {builder: 'claude', builder_pick: 'claude', model_pick: {model:'my-choice'}};
  assert.deepEqual(editModel(unit, available, catalog), {writer:'claude',model:'my-choice',suggested:false});
  assert.equal(editModel({...unit, builder:'demo',builder_pick:'demo'},available,catalog).writer,'demo');
});

test('the compact trigger names the model, falling back to the provider or an action', async () => {
  const { editTriggerText } = await import('../src/components/episode/pictureProvider.ts');
  assert.equal(editTriggerText('codex', 'gpt-example'), 'gpt-example');
  assert.equal(editTriggerText('claude', undefined), 'Claude');
  assert.equal(editTriggerText('kimi', 'CLI default'), 'Kimi');
  assert.equal(editTriggerText('demo', 'demo'), 'Local preview');
  assert.equal(editTriggerText(null, undefined), 'Choose model');
});
