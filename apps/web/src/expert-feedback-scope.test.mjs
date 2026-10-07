import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('./main.jsx', import.meta.url), 'utf8');
const view = source.slice(source.indexOf('function CapabilityImageView('), source.indexOf('function FavoritesPage('));

test('run expert feedback reads and writes carry the selected run scope', () => {
  assert.match(view, /requestResult\(`\/runs\/\$\{encodedRunId\}\/expert-feedback`, \{headers: deepScopeHeadersForRun\(run\)\}\)/);
  assert.match(view, /requestResult\(`\/runs\/\$\{encodedRunId\}\/expert-feedback`, \{method: 'POST', headers: \{\.\.\.deepScopeHeadersForRun\(run\),/);
  assert.match(view, /expert-feedback\/\$\{encodeURIComponent\(feedbackId\)\}\/rollback`[\s\S]*?\.\.\.deepScopeHeadersForRun\(run\)/);
});
