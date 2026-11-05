import {useEffect,useState} from 'react';
import {Enrollment,DecisionButtons} from './Approvals';
import {DestroyProof,EffectCard,Facts,Json,Signals,Status} from './components';
import type {KeySlot} from './crypto';
import {useCall} from './useCall';
import {DemoBar} from './Demo';

type Notice=(message:string)=>void;
export function ConsolePage({notify}:{notify:Notice}){
 const {id,call,calls,choose,error,setCall}=useCall(true);
 const [approver,setApprover]=useState<KeySlot>();
 useEffect(()=>{if(error)notify(error);},[error,notify]);
 const applied=call?.production_status==='APPLIED_VERIFIED';
 const blocked=call?.policy?.outcome==='REJECT'||['DENIED','REFUSED','FAILED_VERIFY'].includes(call?.production_status||'');
 const unmatched=call?.claim_comparison?.filter(item=>item.effect_id===null&&item.mismatch)||[];
 const receipts=calls.filter(item=>['APPLIED_VERIFIED','DENIED','REFUSED','FAILED_VERIFY','BLOCKED','NOT_APPLIED'].includes(item.production_status));
 return <section className="workspace console-workspace">
  {new URLSearchParams(location.search).get('demo')==='1'&&<DemoBar selected={id} choose={choose} notify={notify}/>}
  <div className="workspace-top"><div><div className="eyebrow">IDENTITY CHANGE CONTROL ROOM</div><h1>The Gate.</h1><p className="note">Actual effects. Exact consent. Independent verification.</p></div>
   <div className="toolbar"><select className="call-picker" value={id||''} onChange={e=>choose(e.target.value||null)} aria-label="Select a call"><option value="">Select a call</option>{calls.map(item=><option key={item.call_id} value={item.call_id}>{item.call_id.slice(0,8)} · {item.status.replaceAll('_',' ')}</option>)}</select><a className="button" href="/call">New call ↗</a></div>
  </div>
  {call?.realm==='acme-guest'&&<p className="preview">Guest realm · test signers are simulated. Identity changes and executor verification are real.</p>}
  {call?.workload_origin==='operator_scripted_fault'&&<p className="preview" role="note">Scripted operator containment replay. The commands and state changes are real; the benign agent claim is simulated. No planner generated these commands.</p>}
  {call?.workload_origin==='operator_containment_test'&&<p className="preview">Operator-scripted containment workload. Limits, commands and host-survival checks are real. No planner generated the workload; no production apply is requested.</p>}
  {call?.containment_result&&<div className="containment-checks">{Object.entries(call.containment_result.checks).map(([key,passed])=><span className={passed?'check-passed':'check-failed'} key={key}>{passed?'PASS':'FAIL'} · {key.replaceAll('_',' ')}</span>)}</div>}
  <div className="panel-heading"><Status value={call?.status||(id?'LOADING_CALL':undefined)}/><span className="call-id">{call?.call_id||'Select a call to inspect its evidence'}</span></div>
  <div className={'gate-workspace '+(applied?'gate-passed':blocked?'gate-blocked':'')}>
   <section className="twin-side">
    <div className="panel-heading"><div><div className="eyebrow">DISPOSABLE / ISOLATED</div><h2>Twin changes</h2></div><span className="subtle">{call?`${call.effects.length} effect${call.effects.length===1?'':'s'}`:'—'}</span></div>
    {applied?<div className="passed-placeholder"><span className="eyebrow">SIGNED · APPLIED · RE-READ</span><h3>Exact effects passed the Gate.</h3><p>The approved changes appear in production with independent verification.</p></div>:call?.effects.length?call.effects.map(effect=><EffectCard key={effect.id} effect={effect} call={call}/>):<p className="empty">{call?.busy?'The agent is working in the twin. Actual effects will appear here.':call?'No identity changes were observed.':'Choose a call to inspect the changes the agent actually made.'}</p>}
    {unmatched.length>0&&<details className="unmatched-claims"><summary>MISMATCH · claims without observed effects</summary><Json value={unmatched}/></details>}
    {call&&<><Facts call={call}/><DestroyProof call={call}/></>}
   </section>
   <div className="gate-divider"><span>{applied?'VERIFIED':blocked?'BLOCKED':'EXACT HASH · SIGNATURES'}</span></div>
   <section className="production-side">
    <div className="panel-heading"><div><div className="eyebrow">INDEPENDENT EXECUTOR</div><h2>Production</h2></div><Status value={call?.production_status||(id?'LOADING':'NOT_OBSERVED')}/></div>
    {applied&&call?<div className="verified-effects" aria-live="polite">{call.effects.map(effect=><EffectCard key={effect.id} effect={effect} call={call}/>)}</div>:<div className="production-idle"><p className="large-state">{call?.production_status==='DENIED'?'Denied. Unchanged.':!call?(id?'Loading evidence…':'Select a call.'):call.production_status==='UNCHANGED'?'Unchanged.':call.production_status.replaceAll('_',' ')}</p><p>{blocked?'This proposal did not pass the Gate.':'Only the executor can apply signed effects after its own policy and drift checks.'}</p>{call?.policy&&<><Status value={call.policy.outcome}/><p>{call.policy.rule_ids.join(' · ')}</p></>}</div>}
    {call?.change_set_hash&&<div className="hash">CHANGE SET SHA-256<br/>{call.change_set_hash}</div>}
    {Boolean(call?.receipt)&&<a className="button receipt-link" href={'/receipts/'+call!.call_id}>Verify signed receipt ↗</a>}
   </section>
  </div>
  <section className="console-decisions"><div><h2>Operator decision</h2><p>Approve the exact frozen proposal. Device requirements remain enforced.</p>{call&&<DecisionButtons call={call} slot={approver} notify={notify} onDone={setCall}/>}</div><details className="operator-key" open={!approver}><summary>Operator signing key</summary><Enrollment kind="approver" identity="hassan" notify={notify} onSlot={setApprover}/></details></section>
  <Signals call={call}/>
  <section className="logs"><div><div className="panel-heading"><h2>Tool activity</h2><span className="eyebrow">TWIN ONLY</span></div>{call?.tool_log.length?call.tool_log.map(tool=><details className="log-row" key={tool.id}><summary>{tool.name}<span className="time">{tool.finished_at?'FINISHED':'RUNNING'}</span></summary><Json value={tool.arguments}/>{tool.result!==undefined&&<Json value={tool.result}/>}</details>):<p className="empty">No tool calls selected.</p>}</div><div><div className="panel-heading"><h2>Egress & tripwires</h2><span className="eyebrow">DEFAULT DENY</span></div>{call?.egress.length?call.egress.map((event,index)=><div className="event-row" key={event.ts+index}><span className={event.kind==='TRIPWIRE'||event.allowed===false?'denied':''}>{event.kind==='TRIPWIRE'?'TRIPWIRE · KILLED':event.allowed?'ALLOWED':'DENIED'}</span> {event.host||event.channel} {event.kill_latency_seconds!==undefined?(event.kill_latency_seconds*1000).toFixed(1)+' ms':''}<br/>{event.ts}</div>):<p className="empty">No egress observed for this call.</p>}</div></section>
  <section className="receipt-history"><div className="panel-heading"><h2>Signed receipts</h2><span className="eyebrow">VERIFY IN YOUR BROWSER</span></div>{receipts.length?receipts.map(item=><a href={'/receipts/'+item.call_id} key={item.call_id}><code>{item.call_id.slice(0,8)}</code><span>{item.realm}</span><Status value={item.production_status}/><span>Open receipt ↗</span></a>):<p className="empty">Receipts appear after the executor records a decision.</p>}</section>
 </section>;
}
