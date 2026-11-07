import {useEffect,useRef,useState} from 'react';
import type {Call} from './types';

const steps:Record<string,string>={
 lookup_employee:'Checking the employee directory',
 twin_admin:'Running Keycloak admin inside the twin',
 twin_exec:'Running code inside the twin',
 open_url:'Opening the page in the twin browser',
 request_device_confirmation:'Freezing the twin and deriving the exact effects',
 end_call:'Writing the claimed changes',
};

export function useElapsed(active:boolean){
 const [started,setStarted]=useState<number>();
 const [now,setNow]=useState(()=>Date.now());
 useEffect(()=>{
  if(!active){setStarted(undefined);return;}
  setStarted(Date.now());setNow(Date.now());
  const timer=setInterval(()=>setNow(Date.now()),500);
  return()=>clearInterval(timer);
 },[active]);
 return started===undefined?0:Math.max(0,Math.floor((now-started)/1000));
}

export const clock=(seconds:number)=>Math.floor(seconds/60)+':'+String(seconds%60).padStart(2,'0');

/* Live progress for one agent turn. Steps come from the call's real tool log, recorded after the turn began. */
export function TurnProgress({call,active}:{call:Call|null;active:boolean}){
 const elapsed=useElapsed(active);
 const baseline=useRef(0);
 useEffect(()=>{if(active)baseline.current=call?.tool_log.length??0;},[active]); // eslint-disable-line react-hooks/exhaustive-deps
 if(!active)return null;
 const recent=(call?.tool_log??[]).slice(baseline.current).slice(-5);
 return <div className="turn-progress" role="status" aria-live="polite">
  <div className="progress-head"><span><span className="spinner"/>Working in the twin</span><code>{clock(elapsed)}</code></div>
  <ol>
   <li className={recent.length?'done':'running'}>Planning with Vultr Serverless Inference</li>
   {recent.map(item=><li key={item.id} className={item.finished_at?'done':'running'}>{steps[item.name]??item.name}</li>)}
  </ol>
  <small>A turn usually takes 20–60 s. The agent works in a real, disposable Keycloak twin; nothing reaches production until the exact effects are signed.</small>
 </div>;
}
