import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import vm from "node:vm";

test("four comparison items form two balanced rows with a gutter", () => {
  const cards = [];
  const script = readFileSync(new URL("../../src/design_agent/episode/components/comparison.js", import.meta.url), "utf8");
  vm.runInNewContext(script, {items:[1,2,3,4], n:4, left:0, top:0, w:1200, h:800, size:40,
    variant:"side-by-side", colors:{}, node(){}, label(){}, reveal(){}, words:String,
    rect(x,y,w,h){cards.push({x,y,w,h});}});
  assert.equal(cards[0].x, cards[2].x);
  assert.ok(cards[1].x - cards[0].x - cards[0].w >= 20);
  assert.ok(Math.abs(cards[0].y - (800 - cards[3].y - cards[3].h)) < 2);
});
