import {guestHeaders} from './api';
import {useEffect,useRef,useState} from 'react';
import {clock,useElapsed} from './Progress';

type Notice = (message:string) => void;
type ClipSource = 'microphone' | 'synthetic_stock';

export function useVoiceTurn(notify:Notice){
 const [sending,setSending]=useState(false);
 const [reply,setReply]=useState<{url:string;started:number}>();
 const [latency,setLatency]=useState<number>();
 const audio=useRef<HTMLAudioElement>(null);
 const request=useRef<AbortController|null>(null);

 useEffect(()=>{
  if(!reply)return;
  setLatency(undefined);
  void audio.current?.play().catch(()=>notify('Tap play to hear the reply.'));
  return()=>URL.revokeObjectURL(reply.url);
 },[notify,reply]);
 useEffect(()=>()=>request.current?.abort(),[]);

 async function send(callId:string,clip:Blob,started:number,source:ClipSource){
  if(request.current)return;
  const controller=new AbortController();
  request.current=controller;
  setSending(true);
  setReply(undefined);
  try{
   const response=await fetch('/api/calls/'+encodeURIComponent(callId)+'/audio',{
    method:'POST',body:clip,signal:controller.signal,headers:{
     ...guestHeaders(callId),'Content-Type':clip.type || 'audio/wav','X-Callback-Audio-Source':source,
    },
   });
   if(response.status===204){notify('The reply is available in the transcript.');return;}
   if(!response.ok){
    const error=await response.json().catch(()=>({}));
    throw new Error(error.detail || error.error || 'Voice turn failed. You can send a text request.');
   }
   const wav=await response.blob();
   if(!controller.signal.aborted)setReply({url:URL.createObjectURL(wav),started});
  }catch(e){
   if(!controller.signal.aborted)notify(e instanceof Error?e.message:'Voice turn failed.');
  }finally{
   request.current=null;
   setSending(false);
  }
 }

 const player=reply&&<div className="voice-reply">
  <audio controls aria-label="Callback spoken reply" ref={audio} src={reply.url} onPlaying={()=>{
   if(latency===undefined)setLatency(Math.round(performance.now()-reply.started));
  }}/>
  {latency!==undefined&&<small data-playback-ms={latency}>{(latency/1000).toFixed(1)} s to playback</small>}
 </div>;
 return {sending,send,player};
}

export function PushToTalk({callId,disabled,notify}:{callId:string;disabled:boolean;notify:Notice}){
 const [recording,setRecording]=useState(false);
 const held=useRef(false);
 const recorder=useRef<MediaRecorder|null>(null);
 const timer=useRef<number | undefined>(undefined);
 const {send,sending,player}=useVoiceTurn(notify);
 const elapsed=useElapsed(sending);

 function stop(){
  held.current=false;
  window.clearTimeout(timer.current);
  const active=recorder.current;
  if(active?.state==='recording')active.stop();
 }

 useEffect(()=>()=>{
  held.current=false;
  window.clearTimeout(timer.current);
  const active=recorder.current;
  if(active){active.onstop=null;active.stream.getTracks().forEach(track=>track.stop());}
 },[]);

 async function start(){
  if(held.current||recorder.current||disabled||sending)return;
  if(!navigator.mediaDevices?.getUserMedia||!window.MediaRecorder){
   notify('Microphone recording is unavailable. You can type below.');return;
  }
  held.current=true;
  try{
   const stream=await navigator.mediaDevices.getUserMedia({audio:{channelCount:1}});
   if(!held.current){stream.getTracks().forEach(track=>track.stop());return;}
   let active:MediaRecorder;
   try{
    const mimeType=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type=>MediaRecorder.isTypeSupported(type));
    active=new MediaRecorder(stream,mimeType?{mimeType,audioBitsPerSecond:32000}:undefined);
   }catch(e){stream.getTracks().forEach(track=>track.stop());throw e;}
   const chunks:Blob[]=[];
   const started=performance.now();
   active.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
   active.onstop=()=>{
    const ended=performance.now();
    stream.getTracks().forEach(track=>track.stop());
    recorder.current=null;
    setRecording(false);
    if(ended-started<250){notify('Hold while speaking, then release to send.');return;}
    void send(callId,new Blob(chunks,{type:active.mimeType}),ended,'microphone');
   };
   active.onerror=()=>{
    active.onstop=null;
    stream.getTracks().forEach(track=>track.stop());
    recorder.current=null;
    held.current=false;
    setRecording(false);
    notify('Microphone recording failed. You can type below.');
   };
   recorder.current=active;
   active.start();
   setRecording(true);
   timer.current=window.setTimeout(stop,29_000);
  }catch{
   held.current=false;
   notify('Microphone access is unavailable. You can type below.');
  }
 }

 return <div className="voice-controls">
  <button type="button" className={recording?'recording':''} aria-pressed={recording}
   disabled={!recording&&(disabled||sending)}
   onPointerDown={e=>{if(e.button!==0)return;e.currentTarget.setPointerCapture(e.pointerId);void start();}}
   onPointerUp={stop} onPointerCancel={stop} onLostPointerCapture={stop} onBlur={stop}
   onKeyDown={e=>{if(e.code==='Space'){e.preventDefault();if(!e.repeat)void start();}}}
   onKeyUp={e=>{if(e.code==='Space'){e.preventDefault();stop();}}}>
   {recording?'Release to send':sending?'Processing voice…':'Hold to talk'}
  </button>
  <small>{recording?'Recording · up to 29 s':sending?'Transcribing → planning in the twin → speaking the reply · '+clock(elapsed)+' (usually under a minute)':'Hold with mouse, touch, or Space'}</small>
  {player}
 </div>;
}
