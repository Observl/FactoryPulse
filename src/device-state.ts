export type DeviceState={status?:string;review_required?:boolean;latest_reading?:{failure?:number}};
export function deviceState(device:DeviceState):{kind:string;label:string}{
 const status=(device.status||'').trim();
 if(device.latest_reading?.failure===1||/故障|损坏|失效|fault|failed|breakdown/i.test(status))return {kind:'fault',label:'故障'};
 if(/未启动|未开机|停机|停用|关闭|待机|offline|stopped|idle/i.test(status))return {kind:'offline',label:'未启动 / 已停机'};
 if(device.review_required===true||/预警|告警|异常|warning|alarm/i.test(status))return {kind:'warning',label:'预警'};
 if(/正常|运行|在线|normal|running|online/i.test(status))return {kind:'normal',label:'正常运行'};
 return {kind:'unknown',label:'状态未知'};
}
