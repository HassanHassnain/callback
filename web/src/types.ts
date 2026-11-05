export interface Effect {
 id:string; type:string; realm:string; target:{user_id:string|null;username:string|null};
 before:unknown; after:unknown; reversible:boolean;
 evidence:{tool_call_ids:string[];screenshot_key?:string;vision_verdict?:{verdict:string;reason:string}};
}
export interface Proof {docker_inspect:string;container_id:string;observed_at:string}
export interface Event {ts:string;kind:string;host?:string;allowed?:boolean;channel?:string;kill_latency_seconds?:number}
export interface Policy {outcome:string;rule_ids:string[];auto_eligible?:boolean;requires_device?:string[];requires_human?:boolean}
export interface CallSummary {call_id:string;realm:string;status:string;created_at:string;production_status:string}
export interface Call extends CallSummary {
 signatures?:unknown[]; containment_result?:{action:string;checks:Record<string,boolean>;execution:unknown};
 change_set?:unknown; receipt?:unknown; verified_decisions?:{devices:string[];approvers:string[]};
 busy?:boolean; error?:string; change_set_hash?:string; snapshot_quality?:{quality:string;complete:boolean};
 workload_origin?:string; simulated_claims?:boolean;
 transcript:{role:string;text:string;ts:string}[]; effects:Effect[]; egress:Event[];
 tool_log:{id:string;name:string;arguments:unknown;result?:unknown;started_at:string;finished_at?:string}[];
 moderation:{flagged:boolean;flags:string[]}[];risk:Record<string,number|string>;policy?:Policy;
 claim_comparison?:{effect_id:string|null;mismatch:boolean;reason?:string}[]; destroy_proof?:Proof;
 twin:{twin_id:string;boot_seconds?:number;limits?:{runtime:string;memory_bytes:number;nano_cpus:number;pids_limit:number}};
}
