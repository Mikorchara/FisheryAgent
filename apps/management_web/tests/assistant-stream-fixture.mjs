// Synthetic safe events only. Actual SDK -> HTTP frames are also tested by the Python bridge.
export const profile={mode:'BOUNDED_MULTI_ROUND',can_send:true,max_model_requests:3,
  revision:'stream-revision',release_status:'local_experimental',max_output_tokens:512};
export const expected={request_id:'request',epoch:'epoch',revision:profile.revision,device_id:'pond-a',
  max_output_tokens:512,release_status:profile.release_status};
export function events(){
  const activity={activity_schema_version:2,request_id:'request',revision:1,state:'COMPLETED',
    budget:{tool_calls:2,tool_rounds:2,model_requests:3},counts:{model_requests_started:1,tool_attempts:0,tools_executed:0},
    steps:[{seq:1,kind:'model',request_index:1,request_started:true,state:'COMPLETED',outcome:'final_answer'}],aggregate_usage:{total_tokens:5}};
  return [
    {kind:'start',transport:'streaming',max_model_requests:3,execution_revision:profile.revision,
      device_id:'pond-a',max_output_tokens:512,release_status:profile.release_status},
    {kind:'preview_reset',request_index:1},
    {kind:'preview',request_index:1,text:'临时 <img src=x> 🐟',provisional:true,preview_truncated:false},
    {kind:'final',result:{successful_turn:true,status:'completed',error_code:null,trace_recorded:true,
      request_id:'request',device_id:'pond-a',transport:'streaming',execution:profile,activity,
      final_text:'正式回答 🐟',completed_at:'2026-10-15T01:00:00Z',final_finish_reason:'stop'}}
  ].map((e,i)=>({event_schema_version:1,request_id:'request',epoch:'epoch',seq:i+1,...e}));
}
export const encode=rows=>rows.map(e=>`id: ${e.seq}\ndata: ${JSON.stringify(e)}\n\n`).join('');
export function response(text,{chunkSize=23,eof=true}={}){
  const bytes=new TextEncoder().encode(text);let position=0,closed=false;
  const reader={read:async()=>position>=bytes.length?eof?{done:true}:new Promise(()=>{}):
    {done:false,value:bytes.slice(position,position+=chunkSize)},cancel:async()=>{closed=true;},releaseLock:()=>{}};
  return {headers:new Headers({'Content-Type':'text/event-stream'}),body:{getReader:()=>reader},closed:()=>closed};
}
