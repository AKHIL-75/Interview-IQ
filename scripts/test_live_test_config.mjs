import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

test('cleaned frontend live scripts skip clearly before login without configuration', () => {
  const env = { ...process.env };
  for (const key of Object.keys(env)) if (key.startsWith('IIQ_TEST_')) delete env[key];
  env.IIQ_TEST_CONFIG_FILE = '';
  for (const name of ['test_phase12_401_flow.js', 'test_phase12_multitab.js',
    'test_phase12_phase13_foundation.js', 'verify_real_tester_journey.js', 'verify_phase15_1_e2e_state_flow.js']) {
    const result = spawnSync(process.execPath, [`scripts/${name}`], { env, encoding: 'utf8', timeout: 10000 });
    assert.equal(result.status, 0, name);
    assert.match(result.stdout, /^SKIP: Provision test accounts locally;/, name);
    assert.equal(result.stderr, '', name);
    const source = readFileSync(`scripts/${name}`, 'utf8');
    assert.doesNotMatch(source, /password\s*:\s*['"][^'"]+['"]/, name);
    assert.doesNotMatch(source, /access_token\?*\.slice\(/, name);
  }
});

test('environment-only helper never prints account values', () => {
  const source = readFileSync('scripts/live_test_config.mjs', 'utf8');
  assert.doesNotMatch(source, /console\.(?:log|error)\([^\n]*(?:\.email|\.password|process\.env)/);
});
