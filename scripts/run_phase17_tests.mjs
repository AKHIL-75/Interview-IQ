import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';
const outfile = 'scripts/.phase17.test.cjs';
try {
  await build({ entryPoints: ['scripts/test_phase17.jsx'], outfile, bundle: true, platform: 'node',
    format: 'cjs', jsx: 'automatic', packages: 'external', plugins: [{ name: 'controlled-auth', setup(b) {
      b.onResolve({ filter: /lib\/supabase$/ }, () => ({ path: 'auth', namespace: 'test' }));
      b.onLoad({ filter: /.*/, namespace: 'test' }, () => ({ contents: `
        export const supabase = new Proxy({}, { get: (_,key) => globalThis.sdk[key] });
        export const setGlobalAccessToken = token => { globalThis.currentToken = token; };
        export const getAuthProviderSettings = () => globalThis.providerSettings();
      ` }));
    }}] });
  process.exitCode = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' }).status;
} finally { try { unlinkSync(outfile); } catch {} }
