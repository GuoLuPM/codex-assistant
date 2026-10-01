export class ApiError extends Error {constructor(message:string,public status:number,public code?:string){super(message)}}
export async function api<T=any>(path:string,body?:unknown):Promise<T>{
  let response:Response;
  try{response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});}
  catch{throw new ApiError('连接断开了，您的输入还在。请稍后再试。',0)}
  const data=await response.json();
  if(!response.ok)throw new ApiError(data.error??'这一步没有完成，请再试一次。',response.status,data.code);
  return data;
}
export async function uploadFile(task:string,file:File){
  let response:Response;
  try{response=await fetch(`/api/tasks/${task}/inputs`,{method:'POST',headers:{'Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});}
  catch{throw new Error('资料还没传完，请稍后再试。')}
  const data=await response.json();if(!response.ok)throw new Error(data.error);return data;
}
