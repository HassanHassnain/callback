import type {Call,Effect} from './types';

export function Status({value}:{value?:string}){return <span className={'status '+(value||'').toLowerCase().replaceAll('_','-')}>{(value||'NO CALL').replaceAll('_',' ')}</span>;}
export function Json({value}:{value:unknown}){return <pre className="log">{JSON.stringify(value,null,2)}</pre>;}
export function Facts({call}:{call:Call}){const limits=call.twin.limits;return <div className="facts"><div><span>Twin</span><code>{call.twin.twin_id.slice(0,8)}</code></div><div><span>Runtime</span><code>{limits?.runtime||'—'}</code></div><div><span>Memory cap</span><code>{limits?`${limits.memory_bytes/1024/1024} MiB`:'—'}</code></div><div><span>Boot</span><code>{call.twin.boot_seconds?call.twin.boot_seconds.toFixed(2)+' s':'—'}</code></div><div><span>Snapshot</span><code>{call.snapshot_quality?.quality||'initial'}</code></div></div>;}
export function DestroyProof({call}:{call:Call}){return call.destroy_proof?<div className="destroy-proof">TWIN DESTROYED<br/>{call.destroy_proof.docker_inspect}<br/><span className="subtle">{call.destroy_proof.observed_at}</span></div>:null;}
export function describeEffect(effect:Effect):string {
 const after=effect.after as Record<string,unknown>|null;
 const actions:Record<string,string>={
  'user.password.reset':'Set a new temporary password and require a password change at next sign-in.',
  'credential.otp.removed':'Remove this registered MFA credential.',
  'user.required_action.added':`Require ${String(effect.after).replaceAll('_',' ').toLowerCase()} at next sign-in.`,
  'user.required_action.removed':`Remove the ${String(effect.before).replaceAll('_',' ').toLowerCase()} sign-in requirement.`,
  'user.email.changed':`Change email from ${String(effect.before)} to ${String(effect.after)}.`,
  'user.enabled.changed':effect.after?'Enable this account.':'Disable this account.',
  'user.unlocked':'Clear the account lockout.',
  'user.attribute.changed':`Change account attribute: ${String(after?.attribute)}. Review its exact values below.`,
  'group.member.added':`Add membership in ${String(after?.group)}.`,
  'group.member.removed':`Remove membership in ${String(after?.group)}.`,
  'role.granted':`Grant role ${String(after?.role)} in ${String(after?.scope)}.`,
  'role.revoked':`Revoke role ${String(after?.role)} in ${String(after?.scope)}.`,
  'egress.attempted':'Blocked network attempt. This effect cannot reach production.'
 };
 return actions[effect.type]||'Review the exact observed before and after state below.';
}
export function EffectCard({effect,call}:{effect:Effect;call:Call}){
 const blocked=call.policy?.outcome==='REJECT';const visual=effect.evidence.vision_verdict;
 const mismatch=call.claim_comparison?.find(c=>c.effect_id===effect.id)?.mismatch;
 return <article className={'effect '+(blocked?'blocked':'pending')}><div className="effect-type">{effect.type}</div><h3>{effect.target.username||effect.realm}</h3><p className="effect-summary">{describeEffect(effect)}</p><div className="effect-meta"><Status value={blocked?'REJECT':call.policy?.outcome||'PENDING'}/><span>{call.policy?.rule_ids.join(' · ')}</span>{mismatch&&<span className="danger">MISMATCH · unclaimed or misdescribed</span>}</div><details><summary>Compare before / after</summary><div className="diff"><div><span className="label">BEFORE</span><Json value={effect.before}/></div><div><span className="label">AFTER</span><Json value={effect.after}/></div></div></details>{visual&&<div className="vision">VISION · {visual.verdict} — {visual.reason}{effect.evidence.screenshot_key&&<a href={'/api/screenshots/'+encodeURIComponent(effect.evidence.screenshot_key)} target="_blank" rel="noopener">Actual screenshot ↗</a>}</div>}</article>;
}
export function Signals({call}:{call:Call|null}){return <><section className="signals">{['social_engineering','pressure','bypass'].map(key=>{const value=call?.risk[key];const available=typeof value==='number'&&!call?.risk.error;return <div key={key}><div className="signal-label">{key.replaceAll('_',' ')} · peak<b>{available?Math.round(value*100)+'%':'—'}</b></div>{available&&<progress max="1" value={value} aria-label={key}/>}</div>;})}</section><div className="moderation-flags">{call?.risk.error?'Risk classifier unavailable; review escalated. ':''}{[...new Set(call?.moderation.flatMap(m=>m.flagged?m.flags:[])||[])].join(' · ')}</div></>;}
