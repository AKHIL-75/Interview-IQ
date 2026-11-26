import { build } from 'esbuild';
import { spawnSync } from 'node:child_process';
import { unlinkSync } from 'node:fs';
const outfile = 'scripts/.azure-speech.test.cjs';
try {
  await build({ entryPoints: ['scripts/test_azure_speech.jsx'], outfile, bundle: true,
    platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external',
    define: { 'import.meta.env': '{}', 'import.meta.url': '"file:///caption-tests/"' },
    plugins: [{ name: 'offline-adapters', setup(b) {
      b.onResolve({ filter: /^microsoft-cognitiveservices-speech-sdk$/ }, () => ({ path: 'caption-sdk', namespace: 'test' }));
      b.onResolve({ filter: /services\/api$/ }, () => ({ path: 'api', namespace: 'test' }));
      b.onResolve({ filter: /interviewerVoiceService$/ }, () => ({ path: 'voice', namespace: 'test' }));
      b.onResolve({ filter: /lib\/supabase$/ }, () => ({ path: 'auth', namespace: 'test' }));
      b.onLoad({ filter: /.*/, namespace: 'test' }, ({ path }) => ({ loader: 'js', contents:
        path === 'caption-sdk' ? 'export default new Proxy({}, {get:(_,key)=>globalThis.__captionSdk[key]});' :
        path === 'api' ? 'export const transcribeAudio = (...args) => { if(globalThis.__transcribe) return globalThis.__transcribe(...args); throw Error("Unexpected transcription"); };' :
        path === 'voice' ? 'export default new Proxy({}, {get:(_,key)=>(...args)=>globalThis.__voice[key]?.(...args)});' :
        'export const waitForSessionResolution = async () => "mock-token"; export const supabase = {auth:{refreshSession:(...args)=>globalThis.__auth.refreshSession(...args),signOut:async()=>{}}};'
      }));
    }}],
  });
  process.exitCode = spawnSync(process.execPath, ['--test', outfile], { stdio: 'inherit' }).status;
} finally { try { unlinkSync(outfile); } catch {} }
