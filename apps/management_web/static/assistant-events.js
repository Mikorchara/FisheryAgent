// One bounded POST stream. Never reconnect, replay requests or interpret Tool data.
const object=v=>v!==null&&typeof v==='object'&&!Array.isArray(v);
const integer=(v,min,max)=>Number.isSafeInteger(v)&&v>=min&&v<=max;
const bytes=text=>new TextEncoder().encode(text).length;
const invalid=()=>{throw new Error('ASSISTANT_STREAM_EVENT_INVALID');};

export async function readAssistantEvents(response,expected,onEvent=()=>{}){
  if(!response.headers.get('Content-Type')?.toLowerCase().startsWith('text/event-stream')||!response.body)invalid();
  const reader=response.body.getReader(),decoder=new TextDecoder('utf-8',{fatal:true});
  let buffer='',total=0,sequence=0,index=0,terminal=null,activityRevision=-1;
  function checkActivity(activity){
    if(activity===null)return;
    if(!object(activity)||activity.activity_schema_version!==2||activity.request_id!==expected.request_id||
      !integer(activity.revision,0,Number.MAX_SAFE_INTEGER)||activity.revision<activityRevision||
      !['RUNNING','CANCEL_REQUESTED','COMPLETED','FAILED','CANCELLED'].includes(activity.state)||
      activity.budget?.tool_calls!==2||activity.budget?.tool_rounds!==2||activity.budget?.model_requests!==3||
      !Array.isArray(activity.steps)||activity.steps.length>5||!object(activity.counts)||
      !integer(activity.counts.model_requests_started,0,3)||!integer(activity.counts.tools_executed,0,2)||
      !integer(activity.counts.tool_attempts,0,2))invalid();
    for(const [i,step] of activity.steps.entries()){
      if(!object(step)||step.seq!==i+1||!['model','tool'].includes(step.kind)||
        !['ATTEMPTING','RUNNING','COMPLETED','FAILED','CANCELLED','REJECTED'].includes(step.state))invalid();
      if(step.kind==='model'&&!integer(step.request_index,1,3))invalid();
      if(step.kind==='tool'&&(!integer(step.tool_round,1,2)||typeof step.handler_started!=='boolean'))invalid();
    }
    activityRevision=activity.revision;
  }
  function accept(frame){
    if(!frame.trim()||frame.split('\n').every(line=>!line||line.startsWith(':')))return;
    let id=null,data=null;
    for(const line of frame.split('\n')){
      if(!line||line.startsWith(':'))continue;
      if(line.startsWith('id:')&&id===null)id=line.slice(3).trim();
      else if(line.startsWith('data:')&&data===null)data=line.slice(5).trimStart();
      else invalid(); // This API emits exactly one JSON data line, no event/retry directives.
    }
    let event;try{event=JSON.parse(data);}catch(_){invalid();}
    if(!object(event)||event.event_schema_version!==1||event.request_id!==expected.request_id||event.epoch!==expected.epoch||
      !integer(event.seq,1,513)||id!==String(event.seq))invalid();
    if(event.seq<=sequence)return; // Idempotent delivery: never apply an old frame again.
    if(event.seq!==sequence+1||terminal)invalid();
    if(event.seq===1){
      if(event.kind!=='start'||event.transport!=='streaming'||event.max_model_requests!==3||
        event.execution_revision!==expected.revision||event.device_id!==expected.device_id||
        event.max_output_tokens!==expected.max_output_tokens||event.release_status!==expected.release_status)invalid();
    }else if(event.kind==='start')invalid();
    else if(event.kind==='activity'){
      if(!['RUNNING','CANCEL_REQUESTED','COMPLETED','FAILED','CANCELLED'].includes(event.state))invalid();
      checkActivity(event.activity);
    }else if(event.kind==='preview_reset'||event.kind==='preview'){
      if(!integer(event.request_index,1,3))invalid();
      // The channel can announce Request N+1 before re-emitting a reset for completed N.
      // Its envelope seq is current, but it must never clear / replace a newer request preview.
      if(event.kind==='preview_reset'&&event.request_index<index){sequence=event.seq;return;}
      if(event.request_index<index)invalid();
      if(event.kind==='preview'&&(event.request_index!==index||event.provisional!==true||
        typeof event.text!=='string'||bytes(event.text)>16384||typeof event.preview_truncated!=='boolean'))invalid();
      index=event.request_index;
    }else if(['final','error','cancelled'].includes(event.kind)){
      const result=event.result;
      if(event.kind==='final'){
        if(!object(result)||result.request_id!==expected.request_id||result.transport!=='streaming'||
          result.device_id!==expected.device_id||result.execution?.revision!==expected.revision||
          result.successful_turn!==true||result.status!=='completed'||result.error_code!==null||
          result.trace_recorded!==true||result.final_finish_reason!=='stop'||
          typeof result.final_text!=='string'||!result.final_text.trim()||bytes(result.final_text)>65536||
          typeof result.completed_at!=='string'||!Number.isFinite(Date.parse(result.completed_at))||
          result.activity?.state!=='COMPLETED')invalid();
        checkActivity(result.activity);
      }else{
        const code=result?.error_code??event.error_code;
        if(typeof code!=='string'||!/^[A-Z][A-Z0-9_]{0,63}$/.test(code)||
          (event.kind==='cancelled'&&code!=='USER_CANCELLED')||
          (result&&(!object(result)||result.request_id!==expected.request_id||result.successful_turn!==false||
            result.final_text||result.completed_at||!['failed','cancelled'].includes(result.status))))invalid();
        if(result?.activity)checkActivity(result.activity);
      }
      terminal=event;
    }else invalid();
    sequence=event.seq;onEvent(event);
  }
  try{
    while(true){
      const {done,value}=await reader.read();
      if(done){buffer+=decoder.decode();if(buffer.trim()||!terminal)throw new Error('ASSISTANT_STREAM_INTERRUPTED');break;}
      total+=value.byteLength;if(total>8*1024*1024)invalid();
      try{buffer+=decoder.decode(value,{stream:true});}catch(_){invalid();}
      buffer=buffer.replace(/\r\n/g,'\n');
      if(bytes(buffer)>512*1024)invalid();
      let end;while((end=buffer.indexOf('\n\n'))>=0){const frame=buffer.slice(0,end);buffer=buffer.slice(end+2);accept(frame);}
      if(terminal){if(buffer.trim())invalid();break;}
    }
    return terminal.result?{result:terminal.result}:{error_code:terminal.error_code};
  }finally{
    try{await reader.cancel();}catch(_){/* No reconnect or new model request. */}
    reader.releaseLock();
  }
}
