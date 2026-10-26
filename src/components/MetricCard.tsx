import {type ReactNode} from 'react';
import {Button} from './Button';
export function MetricCard({label,value,note,icon,selected,onClick}:{label:string;value:ReactNode;note?:string;icon?:ReactNode;selected?:boolean;onClick:()=>void}){
 return <Button className={'glass-kpi'+(selected?' selected':'')} variant="navigation" onClick={onClick} aria-pressed={selected}><span className="glass-kpi-heading">{label}{icon}</span><strong>{value}</strong>{note&&<span className="glass-kpi-note">{note}</span>}</Button>;
}
