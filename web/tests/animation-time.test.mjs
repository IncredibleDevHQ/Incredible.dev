import assert from "node:assert/strict";
import test from "node:test";
import { animationTime } from "../src/components/episode/animationTime.ts";

test("edited narration maps each beat to its original animation segment", () => {
  const frame = {id:"held", start:40, seconds:2};
  const unit = {start:20, picture:{generation:{clip_lines:{held:[5,15]}}}};
  assert.equal(animationTime(frame, unit, 1, 2), 10);
  assert.equal(animationTime(frame, unit, 10, 20), 10);
  assert.equal(animationTime(frame, unit, 100, 20), 15);
});
test("older pictures use the saved beat clock when clip metadata is absent", () => {
  assert.equal(animationTime({id:"f",start:12,seconds:6},{start:10,picture:{}},2,4),5);
});
