import {useEffect,useState} from 'react';
import {api} from './api';
import {DecisionButtons} from './Approvals';
import {EffectCard,Status} from './components';
import {decrypt,signed} from './crypto';
import type {Box,KeySlot} from './crypto';
import type {Call} from './types';

export const guestSlots=[
 {identity:'isaac.morgan',name:'Isaac Morgan',team:'Sales'},
 {identity:'ava.bennett',name:'Ava Bennett',team:'Engineering'},
 {identity:'liam.foster',name:'Liam Foster',team:'Finance'},
];

type Props={call:Call|null;slot?:KeySlot;notify:(message:string)=>void;onDone:(call:Call)=>void;onReset:()=>void};
export function GuestPhone({call,slot,notify,onDone,onReset}:Props){
 const [password,setPassword]=useState('');
 const [resetting,setResetting]=useState(false);
 const owns=Boolean(call?.guest_lease&&slot?.identity===call.guest_username&&slot?.realm==='acme-guest');
 useEffect(()=>{setPassword('');},[call?.call_id]);
 useEffect(()=>{if(password){const timer=setTimeout(()=>setPassword(''),60000);return()=>clearTimeout(timer);}},[password]);

 async function reveal(){
  if(!owns||!slot||!call?.change_set_hash)return;
  try{
   const binding={call_id:call.call_id,realm:call.realm,username:slot.identity,change_set_hash:call.change_set_hash};
   const proof=await signed(slot,{...binding,purpose:'delivery',ts:new Date().toISOString()});
   const result=await api<{box:Box}>('/api/device/delivery',{method:'POST',body:JSON.stringify(proof)});
   const opened=await decrypt(slot,result.box,binding);
   setPassword(opened.temporary_password);
  }catch(e){notify(e instanceof Error?e.message:'Unable to decrypt the temporary password');}
 }

 async function reset(){
  if(!owns||!slot||!call?.guest_lease)return;
  setResetting(true);
  try{
   const proof=await signed(slot,{purpose:'guest_reset',realm:'acme-guest',username:slot.identity,
    lease_id:call.guest_lease,ts:new Date().toISOString()});
   await api('/api/guest/reset',{method:'POST',body:JSON.stringify(proof)});
   setPassword('');
   onReset();
   notify('Your guest slot was reset.');
  }catch(e){notify(e instanceof Error?e.message:'Unable to reset this guest slot');}
  finally{setResetting(false);}
 }

 return <aside className="context guest-phone"><div className="eyebrow">BROWSER-HELD KEY / ACME-GUEST</div>
  <h2>Simulated device <small>(guest mode)</small></h2>
  <p className="note">This browser signs for your synthetic persona. Review the actual effects before you decide.</p>
  {call&&<Status value={call.status}/>}
  {call?.effects.map(effect=><EffectCard key={effect.id} effect={effect} call={call}/>)}
  {call?.change_set_hash&&<><div className="eyebrow">EXACT CHANGE-SET HASH</div><code className="breakable">{call.change_set_hash}</code></>}
  {call?.status==='AWAITING_DEVICE'&&<DecisionButtons call={call} slot={owns?slot:undefined} notify={notify} onDone={onDone}/>}
  {owns&&call?.status==='APPLIED_VERIFIED'&&<div className="device-secret">
   {password?<><code data-testid="guest-password">{password}</code><button onClick={()=>setPassword('')}>Hide password</button></>:
    <button onClick={reveal}>Reveal temporary password</button>}
  </div>}
  {Boolean(call?.receipt)&&<a className="button" href={'/receipts/'+call?.call_id}>Verify signed receipt ↗</a>}
  {owns&&<button className="guest-reset" disabled={resetting||call?.busy||call?.status==='SUBMITTING'} onClick={reset}>
   {resetting?'Resetting…':'Reset my guest slot'}
  </button>}
 </aside>;
}
