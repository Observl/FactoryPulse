export const timelineTime=(value?:string)=>value?new Date(value.replace(" ","T")).getTime():NaN;
export type TimedItem={id:string;start_at?:string;end_at?:string};
export function layoutIntervals<T extends TimedItem>(items:T[]){
 const ends:number[]=[];
 const placed=items.filter(item=>Number.isFinite(timelineTime(item.start_at))&&timelineTime(item.end_at)>timelineTime(item.start_at)).sort((a,b)=>timelineTime(a.start_at)-timelineTime(b.start_at)||a.id.localeCompare(b.id)).map(item=>{
  const start=timelineTime(item.start_at),end=timelineTime(item.end_at);let lane=ends.findIndex(value=>value<=start);if(lane<0)lane=ends.length;ends[lane]=end;return {...item,lane,start,end,overlap:false};
 });
 for(let i=0;i<placed.length;i++)for(let j=i+1;j<placed.length&&placed[j].start<placed[i].end;j++){placed[i].overlap=true;placed[j].overlap=true}
 return {items:placed,lanes:Math.max(1,ends.length),invalid:items.length-placed.length};
}
