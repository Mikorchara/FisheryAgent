// Exact, fictional multi-session data; never read a user's database in tests.
export const time=seconds=>new Date(Date.UTC(2026,9,14)+seconds*1000).toISOString();
export const point=(seconds,value=6.4,extra={})=>({observed_at:time(seconds),received_at:time(seconds+1),
  window_start:time(seconds-10),window_duration_s:10,session_id:'a',batch_id:`batch-${seconds}`,
  dissolved_oxygen_mg_l:value,...extra});
export function restartHistory(){
  return [[0,64,'a'],[23450,65,'b'],[72000,85,'c']].flatMap(([start,count,session_id])=>
    Array.from({length:count},(_,i)=>point(start+i*10,6.4+(i%9)*.01,{session_id})));
}
