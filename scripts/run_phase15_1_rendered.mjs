import {build} from 'esbuild';
import {spawnSync} from 'node:child_process';
import {unlinkSync} from 'node:fs';
const outfile='scripts/.phase15_1-rendered.test.cjs';
await build({entryPoints:['scripts/test_phase15_1_rendered.jsx'],outfile,bundle:true,platform:'node',format:'cjs',jsx:'automatic',packages:'external',plugins:[{name:'test-adapters',setup(b){
 b.onResolve({filter:/services\/api$/},()=>({path:'api',namespace:'test'}));
 b.onResolve({filter:/services\/client$|^\.\/client$/},()=>({path:'caption-client',namespace:'test'}));
 b.onResolve({filter:/AuthContext$/},()=>({path:'auth',namespace:'test'}));
 b.onResolve({filter:/interviewerVoiceService$/},()=>({path:'voice',namespace:'test'}));
 b.onLoad({filter:/.*/,namespace:'test'},({path})=>({contents:path==='caption-client'?"export default {get:async()=>{globalThis.__sttConfigCalls=(globalThis.__sttConfigCalls||0)+1;return {enabled:false}},post:async()=>{throw Error('Unexpected token request')}}":path==='auth'?"export const useAuth=()=>({user:{id:'test-user'},loading:false})":path==='voice'?"export default new Proxy({}, {get:(_,key)=>(...args)=>globalThis.__voice[key](...args)})":['parseResume','parseJobDescription','analyzeResumeJobMatch','generateInterviewQuestions','evaluateCandidateAnswer','getAdaptiveNextQuestion','startAdaptiveInterview','persistInterviewReport','transcribeAudio','fetchReportById'].map(n=>`export const ${n}=(...args)=>globalThis.__api.${n}(...args);`).join('\n'),loader:'js'}));
}}]});
const result=spawnSync(process.execPath,['--test',outfile],{stdio:'inherit'});
unlinkSync(outfile);process.exitCode=result.status;
