import {readAssistantEvents} from './assistant-events.js';
// Pages consume application DTOs. Provider SDKs / Prompts / Tool internals stay server-side.
async function read(path){const response=await fetch(path,{credentials:'same-origin'});if(!response.ok)throw new Error('MANAGEMENT_SERVICE_UNAVAILABLE');return response.json();}
export const services={
  bootstrap:device=>read('/api/bootstrap'+(device?'?'+new URLSearchParams({device}):'')),
  monitoring:(device,view)=>read(`/api/monitoring?${new URLSearchParams({device,view})}`),
  events:filters=>read(`/api/events?${new URLSearchParams(filters)}`),
  files:filters=>read(`/api/files?${new URLSearchParams(filters)}`),
  ai:{availability:()=>read('/api/ai/status'),
    toolPolicy:()=>read('/api/ai/tool-policy'),
    saveToolPolicy:(value,config)=>aiWrite('/api/ai/tool-policy',value,config),
    bootstrap:device=>read('/api/ai/bootstrap?'+new URLSearchParams({device})),
    prepare:config=>aiWrite('/api/ai/requests',{epoch:config.epoch},config),
    send:(value,config)=>aiWrite('/api/ai/messages',value,config),
    stream:async(value,config,{signal,onEvent,profile})=>{
      const response=await fetch('/api/ai/messages/stream',{method:'POST',credentials:'same-origin',signal,
        headers:{'Content-Type':'application/json','X-Management-AI':config.browser_token},body:JSON.stringify(value)});
      if(!response.ok){const data=await response.json();throw new Error(data.error_code||'AI_SERVICE_UNAVAILABLE');}
      return readAssistantEvents(response,{...value,max_output_tokens:profile.max_output_tokens,
        release_status:profile.release_status},onEvent);
    },
    state:(value,config)=>aiWrite('/api/ai/request-state',value,config),
    cancel:(value,config)=>aiWrite('/api/ai/cancel',value,config)},
};

async function aiWrite(path,value,config){
  const response=await fetch(path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json',
    'X-Management-AI':config.browser_token},body:JSON.stringify(value),keepalive:path==='/api/ai/cancel'});
  const data=await response.json();
  if(data.result)return data; // Preserve safe failed/cancelled Activity; never commit it as a success.
  if(!response.ok)throw new Error(data.error_code||'AI_SERVICE_UNAVAILABLE');
  return data;
}
