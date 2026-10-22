import {deviceState,type DeviceState} from './device-state';
export function DeviceIndicator({device={},text=false}:{device?:DeviceState;text?:boolean}){
 const state=deviceState(device);
 return <span className="device-state-label" title={state.label}><span className={'device-state-dot '+state.kind} role="img" aria-label={state.label}/>{text&&<span>{state.label}</span>}</span>;
}
