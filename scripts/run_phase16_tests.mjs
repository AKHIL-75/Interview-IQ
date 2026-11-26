import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';
const outfile = 'scripts/.phase16.test.cjs';
try {
  await build({ entryPoints: ['scripts/test_phase16.jsx'], outfile, bundle: true,
    platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external',
    define: { 'import.meta.env': '{}' }, plugins: [{ name: 'auth-adapter', setup(b) {
      b.onResolve({ filter: /lib\/supabase$/ }, () => ({ path: 'auth', namespace: 'test' }));
      b.onLoad({ filter: /.*/, namespace: 'test' }, () => ({ contents:
        'export const supabase={auth:{refreshSession:(...a)=>globalThis.auth.refresh(...a),signOut:()=>globalThis.auth.signOut()}}; export const waitForSessionResolution=async()=>globalThis.auth.token;' }));
    }}] });
  process.exitCode = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' }).status;
} finally { try { unlinkSync(outfile); } catch {} }
