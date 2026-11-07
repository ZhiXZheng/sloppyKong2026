// Regression checks for the offline browser simulation's dry-ground pathfinder.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const ts = require('typescript');
const source = fs.readFileSync('src/simulation/agents.ts', 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020
}}).outputText;
const output = {};
new Function('exports', compiled)(output);
const { findPath } = output;
function grid() {
  return Array.from({ length: 3 }, (_, y) => Array.from({ length: 3 }, (_, x) =>
    ({ x, y, isFlooded: false, waterDepth: 0, isSubmergedRoad: false, elevation: 1 })));
}
for (const depth of [1, 2, 3]) {
  const cells = grid();
  Object.assign(cells[1][1], { isFlooded: true, waterDepth: depth, isSubmergedRoad: true });
  const path = findPath({ x: 0, y: 1 }, { x: 2, y: 1 }, cells);
  assert.equal(path.length, 4);
  for (const p of path) assert.equal(cells[p.y][p.x].isFlooded, false);
  assert.deepEqual(findPath({ x: 0, y: 1 }, { x: 1, y: 1 }, cells), []);
}
const blocked = grid();
for (const row of blocked) row[1].isFlooded = true;
assert.deepEqual(findPath({ x: 0, y: 1 }, { x: 2, y: 1 }, blocked), []);
console.log('Browser pathfinding passed: water depths, submerged roads, flooded goals, and unreachable targets.');
