import test from 'node:test';
import assert from 'node:assert/strict';
import { createSubmissionPipeline } from '../src/services/submissionPipeline.js';
import BrowserSpeechProvider from '../src/services/browserSpeechProvider.js';
import { AudioCapture } from '../src/services/audioCapture.js';
const score = { score: 75, technicalAccuracy: 75, relevance: 80, depth: 65, clarity: 90, strengths: ['Precise example'], improvements: ['Explain trade-offs'], suggestedAnswer: 'A fuller explanation', answer_status: 'PARTIAL' };
function fixture(overrides = {}) {
  let session = {sessionId:'test', questions:[{id:'q1',question:'Explain a transaction',topic:'SQL'}], currentQuestionIndex:0, answers:[], consecutiveFollowUps:0, currentQuestionStartedAt:Date.now(), interviewConfig:{role:'Engineer',interviewMode:'STATIC'}, draft:{questionId:'q1',text:'My answer'}};
  const calls = [];
  const pipeline = createSubmissionPipeline({getSession:()=>session,save:s=>{session=s;},evaluate:async x=>{calls.push(['evaluate',x]);return score;},adapt:async x=>{calls.push(['adapt',x]);return {decision:'TARGETED_FOLLOW_UP',question:{id:'q2',question:'Explain isolation'},isFollowUp:true};},...overrides});
  return {pipeline,calls,get session(){return session;}};
}
test('Q1 cannot advance or acknowledge before submission',()=>{const f=fixture();assert.equal(f.session.questions.length,1);assert.equal(f.session.answers.length,0);assert.equal(f.calls.length,0);});
test('submit evaluates before adaptive and commits Q2 with full feedback',async()=>{const f=fixture();await f.pipeline.submit('Atomic changes');assert.deepEqual(f.calls.map(c=>c[0]),['evaluate','adapt']);assert.deepEqual(f.calls[1][1].questionHistory,['Explain a transaction']);assert.equal(f.session.questions[1].id,'q2');assert.equal(f.session.answers[0].evaluation.suggestedAnswer,score.suggestedAnswer);assert.equal(f.session.answers[0].adaptiveComplete,true);assert.equal(f.session.draft,null);});
test('double submit shares exactly one request pipeline',async()=>{const f=fixture();await Promise.all([f.pipeline.submit('Answer'),f.pipeline.submit('Answer')]);assert.equal(f.calls.length,2);await f.pipeline.submit('Answer');assert.equal(f.calls.length,2);});
test('evaluation failure preserves draft, has no record and never adapts',async()=>{const f=fixture({evaluate:async()=>{throw Error('offline');}});await assert.rejects(f.pipeline.submit('Answer'),/offline/);assert.equal(f.session.answers.length,0);assert.equal(f.session.questions.length,1);assert.equal(f.session.draft.text,'My answer');assert.equal(f.calls.length,0);});
test('malformed evaluation cannot become fabricated scores',async()=>{const f=fixture({evaluate:async()=>({score:65})});await assert.rejects(f.pipeline.submit('Answer'),/invalid scores/);assert.equal(f.session.answers.length,0);});

test('a failure marker cannot be hidden by a completed status or zero scores',async()=>{
 const f=fixture({evaluate:async()=>({...score,score:0,evaluation_status:'COMPLETED',answer_status:'FAILED'})});
 await assert.rejects(f.pipeline.submit('Answer'),/unavailable/);
 assert.equal(f.session.answers.length,0);assert.equal(f.session.questions.length,1);
});
test('empty answer has no side effects',async()=>{const f=fixture();await assert.rejects(f.pipeline.submit('  '));assert.equal(f.calls.length,0);});
test('adaptive retry reuses successful evaluation after refresh',async()=>{let count=0;const f=fixture({adapt:async()=>{if(!count++)throw Error('network');return {decision:'END_INTERVIEW',end_interview:true};}});await assert.rejects(f.pipeline.submit('Answer'),/network/);assert.equal(f.session.answers[0].adaptiveComplete,false);const restored=JSON.parse(JSON.stringify(f.session));const p=createSubmissionPipeline({getSession:()=>restored,save:s=>Object.assign(restored,s),evaluate:async()=>{throw Error('must not evaluate twice');},adapt:async()=>({decision:'END_INTERVIEW',end_interview:true})});await p.submit('Answer');assert.equal(restored.isInterviewEnded,true);assert.equal(f.calls.filter(c=>c[0]==='evaluate').length,1);});
test('duplicate next question fails without corrupting checkpoint',async()=>{const f=fixture({adapt:async()=>({question:{id:'q1',question:'Explain a transaction'}})});await assert.rejects(f.pipeline.submit('Answer'),/duplicate question/);assert.equal(f.session.questions.length,1);assert.equal(f.session.answers[0].adaptiveComplete,false);});
test('zero evaluation stays zero through feedback and adaptation',async()=>{const f=fixture({evaluate:async()=>({...score,score:0,technicalAccuracy:0})});await f.pipeline.submit("I don't know");assert.equal(f.calls[0][1].evaluation.score,0);assert.equal(f.session.answers[0].feedback.overallScore,0);});
function speech() {const spoken=[];globalThis.window={speechSynthesis:{speaking:false,cancel(){},speak:u=>spoken.push(u)}};globalThis.SpeechSynthesisUtterance=class{constructor(text){this.text=text;}};return {provider:new BrowserSpeechProvider(),spoken};}
test('speech error followed by end produces one error and no success',()=>{const {provider,spoken}=speech();let end=0,error=0;provider.speak('Q1',{onEnd:()=>end++,onError:()=>error++});spoken[0].onerror({error:'failed'});spoken[0].onend();assert.equal(error,1);assert.equal(end,0);});
test('cancel and stale browser events cannot complete a request',()=>{const {provider,spoken}=speech();let end=0;provider.speak('Q1',{onEnd:()=>end++});provider.stop();spoken[0].onerror({error:'canceled'});spoken[0].onend();assert.equal(end,0);});
test('repeat speaks same question; only latest request completes once',()=>{const {provider,spoken}=speech();let end=0;provider.speak('Q1',{onEnd:()=>end++});provider.speak('Q1',{onEnd:()=>end++});spoken[0].onend();spoken[1].onend();spoken[1].onend();assert.deepEqual(spoken.map(u=>u.text),['Q1','Q1']);assert.equal(end,1);});
function recording({empty=false,deferred=false}={}) {let stopped=0,resolve;const stream={getTracks:()=>[{stop:()=>stopped++}]};Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:()=>deferred?new Promise(r=>{resolve=r;}):Promise.resolve(stream)}}});globalThis.window={};globalThis.MediaRecorder=class{static isTypeSupported(){return true;}constructor(){this.state='inactive';this.mimeType='audio/webm';}start(){this.state='recording';}stop(){this.state='inactive';if(!empty)this.ondataavailable?.({data:new Blob(['recorded'])});queueMicrotask(()=>this.onstop?.());}};return {stream,get stopped(){return stopped;},resolve:()=>resolve(stream)};}
test('real recorder adapter finalizes one Blob and stops tracks',async()=>{const f=recording();const c=new AudioCapture();await c.start();const a=c.finish(),b=c.finish();assert.equal(a,b);assert.equal((await a).size,8);assert.equal(f.stopped,1);});
test('cancel does not finalize audio and releases tracks',async()=>{const f=recording();const c=new AudioCapture();await c.start();const pending=c.pending;c.cancel();await assert.rejects(pending,/canceled/);assert.equal(f.stopped,1);});
test('permission resolving after cancel releases late stream',async()=>{const f=recording({deferred:true});const c=new AudioCapture();const started=c.start();c.cancel();f.resolve();assert.equal(await started,null);assert.equal(f.stopped,1);});
test('empty recording raises recoverable error',async()=>{recording({empty:true});const c=new AudioCapture();await c.start();await assert.rejects(c.finish(),/No audio/);});

test('recording keeps every chunk including final stop data and waits for explicit finish',async()=>{
 recording();let recorder;
 globalThis.MediaRecorder=class{static isTypeSupported(){return true;}constructor(){recorder=this;this.mimeType='audio/webm;codecs=opus';this.state='inactive';}start(){this.state='recording';}stop(){this.ondataavailable({data:new Blob([' tail'])});this.state='inactive';queueMicrotask(()=>this.onstop());}};
 const capture=new AudioCapture();await capture.start();
 recorder.ondataavailable({data:new Blob(['start'])});recorder.ondataavailable({data:new Blob([' middle'])});
 assert.equal(recorder.state,'recording');const a=capture.finish(),b=capture.finish();assert.equal(a,b);
 const blob=await a;assert.equal(await blob.text(),'start middle tail');assert.equal(blob.type,'audio/webm;codecs=opus');
});


test('exact synthetic answer is preserved through evaluation and saved progression', async () => {
  const answer = 'At Quartz Harbor, I used a B-tree index on order_id; the canary phrase is violet comet 47.';
  const f = fixture(); await f.pipeline.submit(answer);
  assert.equal(f.calls[0][1].candidateAnswer, answer);
  assert.equal(f.session.answers[0].answer, answer);
  assert.notEqual(f.session.answers[0].evaluation.suggestedAnswer, answer);
});
test('speech provenance reaches evaluation and the submitted transcript is stored verbatim', async () => {
  const answer = 'Find keyword. Prevents reassignment. Static belongs to the class.';
  const f = fixture();
  await f.pipeline.submit(answer, 'speech');
  assert.equal(f.calls[0][1].answerSource, 'speech');
  assert.equal(f.calls[0][1].candidateAnswer, answer);
  assert.equal(f.session.answers[0].answer, answer);
});
for (const boundary of ['evaluate', 'adapt']) test(`late ${boundary} response cannot overwrite another attempt`, async () => {
  let resolve, waiting;
  const f = fixture({ [boundary]: () => new Promise(done => { resolve = done; waiting = true; }) });
  const pending = f.pipeline.submit('Old attempt');
  while (!waiting) await Promise.resolve();
  f.session.sessionId = 'new-attempt'; f.session.answers = [{ questionId: 'q1', answer: 'Current answer' }];
  resolve(boundary === 'evaluate' ? score : { decision: 'END_INTERVIEW', end_interview: true });
  await assert.rejects(pending, /earlier interview attempt/);
  assert.equal(f.session.answers[0].answer, 'Current answer');
  assert.equal(f.session.questions.length, 1);
});
