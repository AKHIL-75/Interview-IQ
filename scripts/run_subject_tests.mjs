import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';
const outfile = 'scripts/.subject.test.cjs';
try {
  await build({ entryPoints: ['scripts/test_subjects.jsx'], outfile, bundle: true, platform: 'node',
    format: 'cjs', jsx: 'automatic', packages: 'external', plugins: [{ name: 'controlled-boundaries', setup(b) {
      b.onResolve({ filter: /AuthContext$/ }, () => ({ path: 'auth', namespace: 'test' }));
      b.onResolve({ filter: /services\/client$|^\.\/client$/ }, () => ({ path: 'client', namespace: 'test' }));
      b.onResolve({ filter: /lib\/supabase$/ }, () => ({ path: 'supabase', namespace: 'test' }));
      b.onLoad({ filter: /.*/, namespace: 'test' }, ({ path }) => ({ contents: path === 'auth'
        ? "export const useAuth=()=>({user:{id:'test-owner'},loading:false,session:{access_token:'fixture'}});"
        : path === 'supabase' ? "export const waitForSessionResolution=async()=> 'fixture';"
        : "export default { post:(...args)=>globalThis.httpPost(...args), get:(...args)=>globalThis.httpGet(...args), upload:(...args)=>globalThis.httpUpload(...args) };" })); 
    }}] });
  process.exitCode = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' }).status;
} finally { try { unlinkSync(outfile); } catch {} }
