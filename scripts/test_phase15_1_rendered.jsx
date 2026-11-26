import React from 'react';
import {readFileSync} from 'node:fs';
import {create,act} from 'react-test-renderer';
import test from 'node:test';
import assert from 'node:assert/strict';
import {MemoryRouter} from 'react-router-dom';
import {InterviewProvider,useInterview} from '../src/context/InterviewContext';
import {ToastProvider} from '../src/context/ToastContext';
import InterviewPage from '../src/pages/InterviewPage';
import FeedbackPage from '../src/pages/FeedbackPage';
import ReportPage from '../src/pages/ReportPage';
import Stage from '../src/components/ImmersiveInterviewStage';
import CameraPreview from '../src/components/CameraPreview';
import ControlBar from '../src/components/InterviewControlBar';
const storage=new Map();globalThis.localStorage={getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)};
let context,spoken=[],submissions=[],transcribes=0,trackStops=0;
globalThis.window={};
globalThis.__voice={stop(){},clearCache(){},getCurrentVoice:()=>({name:'en-US-JennyNeural'}),selectVoice(){},isSpeaking:()=>false,initialize:async()=>true,speak:(text,options)=>spoken.push({text,...options})};
const evalResult={score:80,technicalAccuracy:80,relevance:80,depth:80,clarity:80,strengths:['Accurate mechanism'],improvements:['More detail'],suggestedAnswer:'Explain all steps'};
globalThis.__api={startAdaptiveInterview:async()=>({session_id:'render-test',first_question:{id:'q1',question:'Opening question'},interview_plan:{},interview_state:{}}),evaluateCandidateAnswer:async()=>evalResult,getAdaptiveNextQuestion:async()=>({decision:'NEXT_TOPIC',question:{id:'q2',question:'Second question'}}),transcribeAudio:async()=>{transcribes++;return {success:true,text:'Editable transcript'};}};
function Probe(){context=useInterview();return <InterviewPage/>;}
function button(root,label){return root.findAllByType('button').find(b=>b.children.flat(Infinity).join('').includes(label)||JSON.stringify(b.toJSON?.()||b.props.children,(_,v)=>typeof v==='function'?undefined:v).includes(label));}

test('new answer feedback renders three marks without requiring a Depth value', async () => {
  storage.clear();
  const oldEvaluate = globalThis.__api.evaluateCandidateAnswer;
  globalThis.__api.evaluateCandidateAnswer = async () => ({
    score: 94, technicalAccuracy: 95, relevance: 95, clarity: 90,
    rubric_version: 'conceptual-v2', answer_status: 'CORRECT',
    strengths: ['The mechanism is correct.'], improvements: ['Optional: Include an example.'],
    suggestedAnswer: 'A different model answer.',
  });
  function FeedbackProbe() { context = useInterview(); return <FeedbackPage />; }
  let view;
  try {
    await act(async () => { view = create(<MemoryRouter><ToastProvider><InterviewProvider><FeedbackProbe /></InterviewProvider></ToastProvider></MemoryRouter>); });
    await act(async () => { context.updateSetup({ candidateProfile: { name: 'Test' }, jobProfile: { role_title: 'Engineer' }, mode: 'Text' }); });
    await act(async () => { await context.startInterview(); await context.submitAnswer('A short correct answer.'); });
    const rendered = JSON.stringify(view.toJSON());
    assert.match(rendered, /Technical Accuracy/);
    assert.match(rendered, /Suggestions to strengthen your answer/);
    assert.match(rendered, /Include an example/);
    assert.doesNotMatch(rendered, /"Depth"|Optional:/);
  } finally {
    globalThis.__api.evaluateCandidateAnswer = oldEvaluate;
    if (view) await act(async () => view.unmount());
  }
});

for (const conceptual of [true, false]) {
  test(`saved ${conceptual ? 'conceptual' : 'historical'} report renders its original rubric`, async () => {
    storage.clear();
    const rubric = conceptual ? { rubric_version: 'conceptual-v2' } : {};
    const score = conceptual ? 94 : 72;
    globalThis.__api.fetchReportById = async () => ({ report: {
      overall_score: score,
      scores: { ...rubric, grade: conceptual ? 'A+' : 'B', technical_accuracy: 95, relevance: 95, clarity: 90, depth: 15 },
      question_analysis: [{
        ...rubric, question: 'How does Java manage memory?', answer_status: 'CORRECT',
        score, technical_accuracy: 95, relevance: 95, clarity: 90, depth: 15,
        improvements: ['Optional: Include an example.'],
      }],
    } });
    let view;
    try {
      await act(async () => { view = create(<MemoryRouter initialEntries={['/report?id=test']}><InterviewProvider><ReportPage /></InterviewProvider></MemoryRouter>); });
      const question = view.root.findAllByType('button').find(item =>
        item.findAllByType('p').some(text => text.children.includes('How does Java manage memory?')));
      assert.ok(question);
      await act(async () => question.props.onClick());
      const rendered = JSON.stringify(view.toJSON());
      assert.match(rendered, new RegExp(`"${score}%"`));
      if (conceptual) {
        assert.match(rendered, /60% Technical Accuracy, 30% Relevance and 10% Clarity/);
        assert.match(rendered, /Suggestions to strengthen your answer/);
        assert.doesNotMatch(rendered, /"Depth"/);
      } else {
        assert.match(rendered, /"Depth"/);
        assert.match(rendered, /15%/);
        assert.doesNotMatch(rendered, /60% Technical Accuracy/);
      }
    } finally {
      delete globalThis.__api.fetchReportById;
      if (view) await act(async () => view.unmount());
    }
  });
}
test('actual provider/page survives null -> Q1, evaluates and renders Q2 in Text mode',async()=>{
 globalThis.__sttConfigCalls=0;
 storage.clear();let view;
 await act(async()=>{view=create(<MemoryRouter><ToastProvider><InterviewProvider><Probe/></InterviewProvider></ToastProvider></MemoryRouter>);});
 await act(async()=>{context.updateSetup({candidateProfile:{name:'Test'},jobProfile:{role_title:'Engineer'},mode:'Text'});});
 await act(async()=>{await context.startInterview();});
 assert.equal(context.currentQuestion.id,'q1');
 await act(async()=>{await context.submitAnswer('Candidate text');});
 await act(async()=>{assert.equal(context.nextQuestion(),true);});
 assert.equal(context.currentQuestion.id,'q2');
 assert.match(JSON.stringify(view.toJSON()),/Second question/);
 assert.equal(globalThis.__sttConfigCalls,0);
 await act(async()=>view.unmount());
});
function device(){const track={readyState:'live',stop(){trackStops++;this.readyState='ended';}};const stream={getTracks:()=>[track],getVideoTracks:()=>[track]};Object.defineProperty(globalThis,'navigator',{configurable:true,value:{mediaDevices:{getUserMedia:async()=>stream}}});globalThis.MediaRecorder=class{static isTypeSupported(){return true;}constructor(){this.state='inactive';this.mimeType='audio/webm';}start(){this.state='recording';}stop(){this.state='inactive';this.ondataavailable?.({data:new Blob(['audio'])});queueMicrotask(()=>this.onstop?.());}};return {track,stream};}
function props(){return {session:{startedAt:Date.now(),answers:[]},questions:[{id:'q1',question:'Current spoken question'}],currentQuestion:{id:'q1',question:'Current spoken question'},currentQuestionIndex:0,answers:[],setup:{mode:'Voice',questionCount:5},saveDraft(){},submitAnswer:async text=>{submissions.push(text);return {end_interview:false};},nextQuestion:()=>true,handleFinish:async()=>{}};}
test('Done Answering transcribes and submits once without obsolete review controls',async()=>{
 spoken=[];submissions=[];transcribes=0;device();let view;
 await act(async()=>{view=create(<Stage {...props()}/>);});
 await act(async()=>{spoken[0].onEnd();await new Promise(r=>setTimeout(r,430));});
 const done=view.root.findByType(ControlBar).props.onDoneAnswering;
 await act(async()=>{await Promise.all([done(),done()]);});
 assert.equal(transcribes,1);assert.deepEqual(submissions,['Editable transcript']);
 assert.equal(view.root.findAllByType('textarea').length,0);
 assert.equal(view.root.findAllByType('audio').length,0);
 assert.doesNotMatch(JSON.stringify(view.toJSON()),/Review Your Transcribed Answer|Save this recording|Retry full recording|characters/);
 await act(async()=>view.unmount());
});

test('repeat and captions do not submit or change question', async () => {
 spoken=[]; submissions=[]; device(); let view;
 try {
  await act(async () => { view=create(<Stage {...props()}/>); });
  await act(async () => view.root.findByType(ControlBar).props.onRepeatQuestion());
  assert.deepEqual(spoken.map(x=>x.text), ['Current spoken question']);
  await act(async () => spoken[0].onEnd());
  await act(async () => view.root.findByType(ControlBar).props.onRepeatQuestion());
  assert.deepEqual(spoken.map(x=>x.text), ['Current spoken question','Current spoken question']);
  await act(async () => view.root.findByType(ControlBar).props.onToggleCaptions());
  assert.equal(view.root.findByType(ControlBar).props.captionsEnabled,true);
  assert.equal(submissions.length,0);
 } finally { if (view) await act(async () => view.unmount()); }
});
test('TTS failure exposes one question recovery fallback without progressing',async()=>{spoken=[];let advances=0;let view;await act(async()=>{view=create(<Stage {...props()} nextQuestion={()=>advances++}/>);});await act(async()=>spoken[0].onError(Error('voice unavailable')));assert.equal(advances,0);assert.equal(view.root.findAllByType('textarea').length,0);const output=JSON.stringify(view.toJSON());assert.match(output,/Interviewer voice unavailable/);assert.match(output,/Current spoken question/);await act(async()=>view.unmount());});
test('camera attachment and LIVE depend on video dimensions; disable stops tracks',async()=>{const d=device();const video={srcObject:null,readyState:2,videoWidth:640,videoHeight:480,play:async()=>{}};let view;await act(async()=>{view=create(<CameraPreview enabled/>,{createNodeMock:e=>e.type==='video'?video:null});});assert.equal(video.srcObject,d.stream);assert.match(JSON.stringify(view.toJSON()),/LIVE/);await act(async()=>view.update(<CameraPreview enabled={false}/>));assert.equal(video.srcObject,null);assert.equal(d.track.readyState,'ended');await act(async()=>view.unmount());});
test('camera cannot claim LIVE with zero video dimensions',async()=>{device();const video={srcObject:null,readyState:1,videoWidth:0,videoHeight:0,play:async()=>{}};let view;await act(async()=>{view=create(<CameraPreview enabled/>,{createNodeMock:e=>e.type==='video'?video:null});});assert.doesNotMatch(JSON.stringify(view.toJSON()),/LIVE/);await act(async()=>view.unmount());});

test('analysis passes candidate object, job object and numeric threshold without user ID',async()=>{
 storage.clear();let view,received;
 globalThis.__api.analyzeResumeJobMatch=async(...args)=>{received=args;return {match_score:80};};
 await act(async()=>{view=create(<MemoryRouter><ToastProvider><InterviewProvider><Probe/></InterviewProvider></ToastProvider></MemoryRouter>);});
 const candidate={extracted_skills:['Python']},job={required_skills:['Python']};
 await act(async()=>context.updateSetup({candidateProfile:candidate,jobProfile:job}));
 await act(async()=>context.analyzeMatch(0.7));
 assert.deepEqual(received,[candidate,job,0.7]);assert.equal(context.setup.analysis.match_score,80);
 await act(async()=>view.unmount());
});

test('mic stop leaves answer ready; re-record works without opening a review',async()=>{
 spoken=[];submissions=[];transcribes=0;device();let view;
 await act(async()=>{view=create(<Stage {...props()}/>);});
 await act(async()=>{spoken[0].onEnd();await new Promise(r=>setTimeout(r,430));});
 await act(async()=>view.root.findByType(ControlBar).props.onToggleMic());
 assert.equal(transcribes,1);assert.equal(submissions.length,0);
 assert.match(JSON.stringify(view.toJSON()),/Answer ready/);
 await act(async()=>view.root.findByType(ControlBar).props.onToggleMic());
 assert.equal(view.root.findByType(ControlBar).props.isRecording,true);
 await act(async()=>view.unmount());
});

test('failed submission preserves transcript and retries without transcribing again',async()=>{
 spoken=[];submissions=[];transcribes=0;device();let view,attempt=0,advances=0;
 await act(async()=>{view=create(<Stage {...props()} submitAnswer={async text=>{submissions.push(text);if(!attempt++)throw Error('Provider unavailable');return {};}} nextQuestion={()=>{advances++;return true;}}/>);});
 await act(async()=>{spoken[0].onEnd();await new Promise(r=>setTimeout(r,430));});
 await act(async()=>view.root.findByType(ControlBar).props.onDoneAnswering());
 assert.equal(advances,0);assert.match(JSON.stringify(view.toJSON()),/Your answer is preserved/);
 await act(async()=>view.root.findByType(ControlBar).props.onDoneAnswering());
 assert.equal(transcribes,1);assert.deepEqual(submissions,['Editable transcript','Editable transcript']);assert.equal(advances,1);
 await act(async()=>view.unmount());
});

test('empty transcription never submits; microphone can record again',async()=>{
 const original=globalThis.__api.transcribeAudio;spoken=[];submissions=[];device();let view;
 globalThis.__api.transcribeAudio=async()=>({success:true,text:''});
 try {
  await act(async()=>{view=create(<Stage {...props()}/>);});
  await act(async()=>{spoken[0].onEnd();await new Promise(r=>setTimeout(r,430));});
  await act(async()=>view.root.findByType(ControlBar).props.onDoneAnswering());
  assert.equal(submissions.length,0);assert.match(JSON.stringify(view.toJSON()),/No clear speech/);
  await act(async()=>view.root.findByType(ControlBar).props.onToggleMic());
  assert.equal(view.root.findByType(ControlBar).props.isRecording,true);
 } finally {if(view)await act(async()=>view.unmount());globalThis.__api.transcribeAudio=original;}
});

test('unmount during transcription cancels completion without submission',async()=>{
 const original=globalThis.__api.transcribeAudio;spoken=[];submissions=[];device();let view,resolve,pending;
 globalThis.__api.transcribeAudio=()=>new Promise(r=>{resolve=r;});
 try {
  await act(async()=>{view=create(<Stage {...props()}/>);});
  await act(async()=>{spoken[0].onEnd();await new Promise(r=>setTimeout(r,430));});
  await act(async()=>{pending=view.root.findByType(ControlBar).props.onDoneAnswering();});
  await act(async()=>view.unmount());
  await act(async()=>{resolve({success:true,text:'Late transcript'});await pending;});
  assert.equal(submissions.length,0);
 } finally {globalThis.__api.transcribeAudio=original;}
});
