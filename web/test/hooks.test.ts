import { test } from "node:test";
import assert from "node:assert/strict";
import { LineSplitter } from "@clite/shared";

test("apps/shared integration in web workspace: LineSplitter works", () => {
  const splitter = new LineSplitter();
  const lines = splitter.push("line1\nline2\n");
  assert.deepEqual(lines, ["line1", "line2"]);
});
