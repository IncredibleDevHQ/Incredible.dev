import assert from 'node:assert/strict';
import test from 'node:test';
import { handOverWords, jobAddress, jobPlace, kept, laneOf, loadOf, needsYou, pileOf, queueOf } from '../src/production.ts';

const job = (over) => ({ id: `${over.episode ?? 'ep_a'}:${over.unit ?? 'c1.b1.f1'}`, what: 'picture', episode: 'ep_a', unit: 'c1.b1.f1', chapter: 'c1', kind: 'diagram', beats: [2, 3, 4, 5], lines: 4, state: 'todo', agent: 'claude', asked_at: null, started_at: null, ...over });
const episodes = [
  { id: 'ep_a', title: 'HTTP caching, explained', channel: 'launch', channel_id: 'c_1', chapters: [{ id: 'c1', n: 1, question: 'Why?' }, { id: 'c2', n: 2, question: 'How?' }] },
  { id: 'ep_b', title: 'Shipping a fix past the cache', channel: 'brand kit', channel_id: 'c_2', chapters: [{ id: 'c1', n: 1, question: 'What?' }] },
];

test('a job stands in the lane of who has to act on it', () => {
  assert.deepEqual(['todo', 'waiting', 'running', 'go', 'failed', 'done'].map((state) => laneOf(job({ state }))), ['todo', 'agents', 'agents', 'needs', 'needs', 'done']);
  assert.equal(needsYou({ jobs: [job({ state: 'go' }), job({ state: 'failed' }), job({ state: 'running' })] }), 2);
  assert.equal(needsYou(null), 0);
});

test('a job is placed by its episode and chapter, and addressed in its own page', () => {
  assert.equal(jobPlace(job({ chapter: 'c2' }), episodes), 'HTTP caching, explained · Chapter 2');
  assert.equal(jobPlace(job({ what: 'script', chapter: '' }), episodes), 'HTTP caching, explained');
  // its own page, at its chapter and the line its picture starts on
  assert.equal(jobAddress(job({ chapter: 'c2', unit: 'c2.b2.f1' }), episodes), '/c/launch/episode/ep_a?at=c2&line=c2.b2.f1');
  assert.equal(jobAddress(job({ episode: 'ep_b', what: 'script', chapter: '', unit: '' }), episodes), '/c/brand%20kit/episode/ep_b');
});

test('the pile groups what is to make by episode and chapter, in the film\'s order', () => {
  const jobs = [
    job({ unit: 'c2.b1.f1', chapter: 'c2' }),
    job({ unit: 'c1.b2.f1' }),
    job({ unit: 'c1.b4.f1' }),
    job({ unit: 'c1.b6.f1', state: 'done' }),
    job({ episode: 'ep_b', unit: 'c1.b1.f1' }),
    job({ episode: 'ep_b', what: 'script', unit: '', chapter: '', state: 'todo' }),
  ];
  const pile = pileOf(jobs, episodes);
  assert.deepEqual(pile.map((g) => [g.episode.id, g.jobs.length, g.chapters.map((c) => [c.n, c.jobs.map((j) => j.unit)])]), [
    ['ep_a', 3, [[1, ['c1.b2.f1', 'c1.b4.f1']], [2, ['c2.b1.f1']]]],
    ['ep_b', 1, [[1, ['c1.b1.f1']]]],
  ]);
  assert.deepEqual(pileOf([job({ state: 'done' })], episodes), []);
});

test('a filter keeps one episode, one of its chapters, one agent', () => {
  const jobs = [job({ unit: 'a' }), job({ unit: 'b', chapter: 'c2', agent: 'kimi' }), job({ episode: 'ep_b', unit: 'c' })];
  assert.equal(kept(jobs, { episode: '', chapter: '', agent: '' }).length, 3);
  assert.deepEqual(kept(jobs, { episode: 'ep_a', chapter: '', agent: '' }).map((j) => j.unit), ['a', 'b']);
  assert.deepEqual(kept(jobs, { episode: 'ep_a', chapter: 'c2', agent: '' }).map((j) => j.unit), ['b']);
  assert.deepEqual(kept(jobs, { episode: '', chapter: '', agent: 'kimi' }).map((j) => j.unit), ['b']);
});

test('an agent\'s row says how busy it is and what a hand-over comes to', () => {
  const agent = { id: 'claude', title: 'Claude Code', ready: true, models: [], running: 2, waiting: 3, seconds: 300 };
  assert.equal(loadOf(agent), '2 running · 3 waiting');
  assert.equal(loadOf({ ...agent, running: 0, waiting: 0 }), 'Free');
  assert.equal(loadOf({ ...agent, ready: false }), 'Not set up here');
  // five ahead and three more are two rounds of four, five minutes each
  assert.equal(handOverWords(agent, 3), '+3 pictures · about 10 min');
  assert.equal(handOverWords({ ...agent, seconds: null }, 1), '+1 picture');
  // made pictures among them are said: a hand-over draws them again
  assert.equal(handOverWords({ ...agent, seconds: null }, 3, 1), '+3 pictures · 1 drawn again');
  assert.equal(handOverWords({ ...agent, seconds: null }, 1, 1), '+1 picture · drawn again');
  assert.equal(handOverWords({ ...agent, seconds: null }, 2, 2), '+2 pictures · all drawn again');
  assert.equal(handOverWords({ ...agent, running: 0, waiting: 0, seconds: 2400 }, 8), '+8 pictures · about 1h 20m');
  const jobs = [job({ unit: 'w2', state: 'waiting', asked_at: 30 }), job({ unit: 'r', state: 'running', asked_at: 5 }), job({ unit: 'w1', state: 'waiting', asked_at: 10 }), job({ unit: 'k', state: 'running', agent: 'kimi' })];
  const queue = queueOf(jobs, 'claude');
  assert.deepEqual([queue.running.map((j) => j.unit), queue.waiting.map((j) => j.unit)], [['r'], ['w1', 'w2']]);
});
