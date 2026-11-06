import {useEffect,useState} from 'react';
const steps=[
 {title:'Work in the twin.',body:'The agent makes its changes inside a disposable copy of the identity provider.'},
 {title:'Inspect the actual effects.',body:'Trusted snapshots produce the change set, independently of the agent’s description.'},
 {title:'Ask for exact consent.',body:'The registered device signs the exact changes. Privileged requests also need an operator.'},
 {title:'Apply, re-read, verify.',body:'A separate executor checks production, applies the signed effects, then proves what changed.'}
];
export function Walkthrough(){
 const [step,setStep]=useState(0);const [playing,setPlaying]=useState(false);
 useEffect(()=>{if(!playing)return;let current=0;const timer=setInterval(()=>{current++;if(current===steps.length){setPlaying(false);clearInterval(timer);}else setStep(current);},5000);return()=>clearInterval(timer);},[playing]);
 function play(){setStep(0);setPlaying(true);}
 return <section className="walkthrough"><div><div className="eyebrow">A 20-SECOND ILLUSTRATION</div><h2>From request<br/>to verified effect.</h2><p>Explore the boundary, then inspect recorded executions in the Gate.</p><button onClick={play} disabled={playing}>{playing?'Walkthrough playing…':'Play the walkthrough'}</button><a href="/console?demo=1">View real recorded evidence ↗</a></div><div className="walkthrough-process"><div className="process-zones">{['TWIN','EFFECTS','CONSENT','EXECUTOR'].map((label,index)=><button className={step===index?'selected':''} key={label} aria-pressed={step===index} disabled={playing} onClick={()=>setStep(index)}>{label}</button>)}</div><div className="process-progress" aria-hidden="true"><span style={{width:((step+1)/steps.length*100)+'%'}}/></div><article key={step}><h3>{steps[step].title}</h3><p>{steps[step].body}</p></article><small>Conceptual illustration · this does not start a live call.</small></div></section>;
}
