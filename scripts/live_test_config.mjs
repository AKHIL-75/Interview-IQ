// Live tests use provisioned accounts only; values are never logged.
import { readFileSync } from 'node:fs';
import { parseEnv } from 'node:util';

const paths = ['../backend/.env'];
if (process.env.IIQ_TEST_CONFIG_FILE !== '') paths.push('../backend/.env.test.local');
for (const path of paths) {
  try {
    const values = parseEnv(readFileSync(new URL(path, import.meta.url), 'utf8'));
    for (const [key, value] of Object.entries(values)) process.env[key] ??= value;
  } catch (error) {
    if (error.code !== 'ENOENT') throw new Error('Unable to read local live-test configuration');
  }
}

export const testPublicConfig = {
  url: process.env.SUPABASE_URL,
  anonKey: process.env.SUPABASE_ANON_KEY,
};

export function requireTestAccount(label = 'A') {
  const keys = [`IIQ_TEST_${label}_EMAIL`, `IIQ_TEST_${label}_PASSWORD`, 'SUPABASE_URL', 'SUPABASE_ANON_KEY'];
  const missing = keys.filter(key => !process.env[key]);
  if (missing.length) {
    console.log(`SKIP: Provision test accounts locally; missing ${missing.join(', ')}`);
    process.exit(0);
  }
  return { email: process.env[keys[0]], password: process.env[keys[1]] };
}
