// RFC 8785: ECMAScript serialization and UTF-16 property ordering.
export function canonical(value:unknown):string {
 if(value===null||typeof value==='boolean')return JSON.stringify(value);
 if(typeof value==='number'){if(!Number.isFinite(value))throw Error('Non-finite number');return JSON.stringify(value);}
 if(typeof value==='string'){
  for(let i=0;i<value.length;i++){const c=value.charCodeAt(i);if(c>=0xd800&&c<=0xdbff){const n=value.charCodeAt(++i);if(!(n>=0xdc00&&n<=0xdfff))throw Error('Invalid Unicode');}else if(c>=0xdc00&&c<=0xdfff)throw Error('Invalid Unicode');}
  return JSON.stringify(value);
 }
 if(Array.isArray(value))return '['+value.map(canonical).join(',')+']';
 if(typeof value==='object')return '{'+Object.keys(value as object).sort().map(k=>canonical(k)+':'+canonical((value as Record<string,unknown>)[k])).join(',')+'}';
 throw Error('Unsupported canonical value');
}
const bytes=(v:string)=>new TextEncoder().encode(v);
export function unbase64(v:string):Uint8Array<ArrayBuffer>{return Uint8Array.from(atob(v.replaceAll('-','+').replaceAll('_','/')),c=>c.charCodeAt(0));}
function base64(v:ArrayBuffer){return btoa(String.fromCharCode(...new Uint8Array(v))).replaceAll('+','-').replaceAll('/','_').replaceAll('=','');}
export async function fingerprint(v:unknown){return Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes(canonical(v))))).map(x=>x.toString(16).padStart(2,'0')).join('');}
export interface KeySlot {id:string;kind:'device'|'approver';identity:string;realm:string;signing:CryptoKeyPair;encryption?:CryptoKeyPair;publicKey:JsonWebKey;encryptionPublicKey?:JsonWebKey;enrollmentId?:string;bundle?:unknown}
function database():Promise<IDBDatabase>{return new Promise((resolve,reject)=>{const r=indexedDB.open('callback-device-keys',1);r.onupgradeneeded=()=>r.result.createObjectStore('keys',{keyPath:'id'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
export async function loadSlot(id:string):Promise<KeySlot|undefined>{const db=await database();return new Promise((resolve,reject)=>{const tx=db.transaction('keys');const r=tx.objectStore('keys').get(id);r.onsuccess=()=>resolve(r.result);tx.oncomplete=()=>db.close();r.onerror=()=>reject(r.error);});}
export async function saveSlot(slot:KeySlot){const db=await database();return new Promise<void>((resolve,reject)=>{const tx=db.transaction('keys','readwrite');tx.objectStore('keys').put(slot);tx.oncomplete=()=>{db.close();resolve();};tx.onerror=()=>reject(tx.error);});}
export async function createSlot(kind:'device'|'approver',identity:string,realm='acme'){
 const id=`${realm}:${kind}:${identity}`;const old=await loadSlot(id);if(old)return old;
 const signing=await crypto.subtle.generateKey({name:'ECDSA',namedCurve:'P-256'},false,['sign','verify']);
 const encryption=kind==='device'?await crypto.subtle.generateKey({name:'ECDH',namedCurve:'P-256'},false,['deriveBits']):undefined;
 const slot:KeySlot={id,kind,identity,realm,signing,encryption,publicKey:await crypto.subtle.exportKey('jwk',signing.publicKey),encryptionPublicKey:encryption?await crypto.subtle.exportKey('jwk',encryption.publicKey):undefined};
 await saveSlot(slot);return slot;
}
export async function signed(slot:KeySlot,payload:unknown){return {payload,signature:base64(await crypto.subtle.sign({name:'ECDSA',hash:'SHA-256'},slot.signing.privateKey,bytes(canonical(payload))))};}
export async function enrollment(slot:KeySlot){return signed(slot,{kind:slot.kind,identity:slot.identity,realm:slot.realm,public_key:slot.publicKey,ts:new Date().toISOString(),nonce:crypto.randomUUID(),...(slot.encryptionPublicKey?{encryption_public_key:slot.encryptionPublicKey}:{})});}
export interface Envelope {payload:Record<string,unknown>;signature:string;signer_public_key:JsonWebKey}
export async function verifyReceipt(envelope:Envelope){
 const response=await fetch('/executor-pubkey.json',{cache:'no-store'});if(!response.ok)throw Error('Executor public key unavailable');
 const pinned=await response.json();const key=await crypto.subtle.importKey('jwk',pinned,{name:'ECDSA',namedCurve:'P-256'},false,['verify']);
 if(!await crypto.subtle.verify({name:'ECDSA',hash:'SHA-256'},key,unbase64(envelope.signature),bytes(canonical(envelope.payload))))throw Error('Receipt signature did not verify');
 return fingerprint(pinned);
}
export interface Box {version:number;ephemeral_public_key:JsonWebKey;salt:string;nonce:string;ciphertext:string;binding:Record<string,string>}
export async function decrypt(slot:KeySlot,box:Box,expected:Record<string,string>){
 if(!slot.encryption||box.version!==1||canonical(box.binding)!==canonical(expected))throw Error('Encrypted delivery binding differs from this device and call');
 const ephemeral=await crypto.subtle.importKey('jwk',box.ephemeral_public_key,{name:'ECDH',namedCurve:'P-256'},false,[]);
 const shared=await crypto.subtle.deriveBits({name:'ECDH',public:ephemeral},slot.encryption.privateKey,256);
 const material=await crypto.subtle.importKey('raw',shared,'HKDF',false,['deriveKey']);
 const info=bytes('callback-device-delivery-v1\0'+canonical(box.binding));
 const key=await crypto.subtle.deriveKey({name:'HKDF',hash:'SHA-256',salt:unbase64(box.salt),info},material,{name:'AES-GCM',length:256},false,['decrypt']);
 return JSON.parse(new TextDecoder().decode(await crypto.subtle.decrypt({name:'AES-GCM',iv:unbase64(box.nonce),additionalData:bytes(canonical(box.binding))},key,unbase64(box.ciphertext)))) as {temporary_password:string;required_action:string};
}
