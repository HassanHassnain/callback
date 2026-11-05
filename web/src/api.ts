export class APIError extends Error {
 status:number;
 constructor(message:string,status:number){super(message);this.status=status;}
}
export async function api<T>(path:string,options:RequestInit={}):Promise<T>{
 const response=await fetch(path,{...options,headers:{'Content-Type':'application/json',...options.headers}});
 const data=await response.json();
 if(!response.ok)throw new APIError(data.detail||data.error||`Request failed (${response.status})`,response.status);
 return data as T;
}
