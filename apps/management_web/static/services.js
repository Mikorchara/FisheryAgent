// Pages consume application DTOs. Provider SDKs / Prompts / Tool internals stay server-side.
async function read(path){const response=await fetch(path,{credentials:'same-origin'});if(!response.ok)throw new Error('MANAGEMENT_SERVICE_UNAVAILABLE');return response.json();}
export const services={
  bootstrap:device=>read('/api/bootstrap'+(device?'?'+new URLSearchParams({device}):'')),
  monitoring:(device,view)=>read(`/api/monitoring?${new URLSearchParams({device,view})}`),
  events:filters=>read(`/api/events?${new URLSearchParams(filters)}`),
  files:filters=>read(`/api/files?${new URLSearchParams(filters)}`),
  ai:{availability:()=>read('/api/ai/status')},
};
