// Replays conversations recorded from the Python simulator against the JavaScript twin.
// Every answer must be the same bytes. Run: node site/test/twin.test.mjs
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const context = { window: {} };
context.globalThis = context.window;
vm.createContext(context);
for (const file of ['../data/map.js', '../js/twin.js']) {
  vm.runInContext(readFileSync(join(here, file), 'utf8'), context, { filename: file });
}
const Twin = context.window.Twin;
const talks = JSON.parse(readFileSync(join(here, 'vectors.json'), 'utf8'));

let steps = 0;
let failures = 0;
for (const talk of talks) {
  const device = new Twin.Device(1);
  for (const [kind, question, expected] of talk.steps) {
    const request = Twin.unhex(question);
    let answer;
    if (kind === 'pdu') answer = Twin.hex(device.respond(request)).replace(/ /g, '').toLowerCase();
    else {
      const { reply } = device.serveRtu(request);
      answer = reply === null ? null : Twin.hex(reply).replace(/ /g, '').toLowerCase();
    }
    steps += 1;
    if (answer !== expected) {
      failures += 1;
      if (failures <= 5) {
        console.error(`MISMATCH in "${talk.name}", step ${steps}\n  asked    ${question}\n  python   ${expected}\n  twin     ${answer}`);
      }
    }
  }
}
if (failures) {
  console.error(`${failures} of ${steps} answers differ from the Python simulator`);
  process.exit(1);
}
console.log(`twin: ${steps} answers in ${talks.length} conversations, all identical to the Python simulator`);
