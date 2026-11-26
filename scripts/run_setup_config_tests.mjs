import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';
const outfile = 'scripts/.setup-config.test.cjs';
try {
  await build({ entryPoints: ['scripts/test_setup_config.jsx'], outfile, bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external' });
  process.exitCode = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' }).status;
} finally {
  try { unlinkSync(outfile); } catch {}
}
