export class APIError extends Error {
 status:number;
 constructor(message:string,status:number){super(message);this.status=status;}
}
export function guestHeaders(callId:string):Record<string,string>{
 const token=sessionStorage.getItem('callback:guest-token:'+callId);
 return token?{'X-Callback-Guest-Token':token}:{};
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const callId=/^\/api\/calls\/([a-f0-9-]{36})\//.exec(path)?.[1];
 const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...(callId?guestHeaders(callId):{}),...options.headers}});
 const data=await response.json();
 if(!response.ok)throw new APIError(data.detail||data.error||`Request failed (${response.status})`,response.status);
 return data as T;
}
