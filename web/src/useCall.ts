import {useCallback,useEffect,useState} from 'react';
import {api,APIError} from './api';
import type {Call,CallSummary} from './types';

export function useCall(listCalls=false){
 const [id,setId]=useState<string|null>(()=>{const query=new URLSearchParams(location.search).get('call');if(query)return query;try{return localStorage.getItem('callback:v1:call');}catch{return null;}});
 const [call,setCall]=useState<Call|null>(null);
 const [calls,setCalls]=useState<CallSummary[]>([]);
 const [error,setError]=useState('');
 const choose=useCallback((next:string|null)=>{setId(next);setCall(null);try{if(next)localStorage.setItem('callback:v1:call',next);else localStorage.removeItem('callback:v1:call');}catch{/* Storage is optional; the call URL remains shareable. */}const params=new URLSearchParams(location.search);if(next)params.set('call',next);else params.delete('call');history.replaceState(null,'',location.pathname+(params.size?'?'+params.toString():''));},[]);
 useEffect(()=>{
  let active=true;let timer:ReturnType<typeof setTimeout>;
  async function poll(){
   try{
    if(listCalls){const list=await api<CallSummary[]>('/api/calls');if(active){setCalls(list);if(!id&&list.length){choose(list[0].call_id);return;}}}
    if(id){const next=await api<Call>('/api/calls/'+encodeURIComponent(id));if(active)setCall(old=>JSON.stringify(old)===JSON.stringify(next)?old:next);}
   }catch(e){if(active){if(e instanceof APIError&&e.status===404)choose(null);else setError(e instanceof Error?e.message:'Connection failed');}}
   if(active)timer=setTimeout(poll,1500);
  }
  poll();return()=>{active=false;clearTimeout(timer);};
 },[id,listCalls,choose]);
 return {id,call,calls,choose,setCall,error,setError};
}
