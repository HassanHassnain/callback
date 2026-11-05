import {useEffect,useState} from 'react';
import {api} from './api';
interface Beat {id:string;title:string;call_id:string;origin:string}
interface Manifest {mode:string;description:string;beats:Beat[]}
export function DemoBar({selected,choose,notify}:{selected:string|null;choose:(id:string)=>void;notify:(message:string)=>void}){
 const [manifest,setManifest]=useState<Manifest>();
 useEffect(()=>{let live=true;api<Manifest>('/api/demo').then(data=>{if(live)setManifest(data);}).catch(e=>{if(live)notify(e instanceof Error?e.message:'Recorded evidence unavailable');});return()=>{live=false;};},[notify]);
 return <section className="demo-bar"><div><div className="eyebrow">EVIDENCE REPLAY</div><p>{manifest?.description||'Loading recorded executions…'}</p></div><div className="demo-beats">{manifest?.beats.map(beat=><button className={selected===beat.call_id?'selected':''} key={beat.id} onClick={()=>choose(beat.call_id)} aria-pressed={selected===beat.call_id}>{beat.title}<small>{beat.origin}</small></button>)}</div></section>;
}
