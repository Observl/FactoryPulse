import {forwardRef,type ButtonHTMLAttributes,type HTMLAttributes,type ReactNode,Children,isValidElement} from 'react';
export type ButtonVariant='primary'|'secondary'|'link'|'icon'|'navigation';
export type ButtonSize='default'|'compact';
type Props=ButtonHTMLAttributes<HTMLButtonElement>&{variant?:ButtonVariant;size?:ButtonSize;busy?:boolean;busyLabel?:ReactNode;reserveLabel?:ReactNode};
const infer=(className:string):ButtonVariant=>/\bprimary\b/.test(className)?'primary':/text-link|column-sort|header-help/.test(className)?'link':/rail-button|rail-brand|rail-avatar|menu-trigger|modal-close|icon-button/.test(className)?'icon':/tab|workspace-|tree-|glass-kpi|suggestion|mobile-menu-item|maintenance-queues|welcome-action|risk-components|resource-list|onboarding|quick-|shortcut|demo-tag/.test(className)?'navigation':'secondary';
/** The only native button in application source. Loading labels share one reserved slot. */
export const Button=forwardRef<HTMLButtonElement,Props>(function Button({variant,size='default',busy,busyLabel,reserveLabel,className='',children,disabled,type='button',...props},ref){
 const resolved=variant||infer(className),pending=busy===true,reserve=busy!==undefined||busyLabel!==undefined||reserveLabel!==undefined;
 return <button {...props} ref={ref} type={type} className={'ui-button '+className} data-variant={resolved} data-size={size} disabled={disabled||pending} aria-busy={pending||undefined}>{reserve?<><span className="ui-button-face" aria-hidden={pending} style={{visibility:pending?'hidden':'visible'}}>{children}</span><span className="ui-button-face ui-button-busy" aria-hidden={!pending} style={{visibility:pending?'visible':'hidden'}}>{busyLabel??'正在处理…'}</span>{reserveLabel!==undefined&&<span className="ui-button-face" aria-hidden="true" style={{visibility:'hidden'}}>{reserveLabel}</span>}</>:children}</button>;
});
/** Native file input activation with the same surface and dimensions as Button. */
export function FileButton({className='',children,disabled=false,...props}:HTMLAttributes<HTMLLabelElement>&{children:ReactNode;disabled?:boolean}){
 const inputDisabled=Children.toArray(children).some(child=>isValidElement<{type?:string;disabled?:boolean}>(child)&&child.props.type==='file'&&child.props.disabled);
 const inactive=disabled||inputDisabled;
 return <label {...props} className={'ui-button ui-file-button '+className} data-variant={infer(className)} data-size="default" role="button" tabIndex={inactive?-1:0} aria-disabled={inactive} onKeyDown={event=>{props.onKeyDown?.(event);if(!inactive&&(event.key==='Enter'||event.key===' ')){event.preventDefault();event.currentTarget.querySelector<HTMLInputElement>('input[type=file]')?.click()}}}>{children}</label>;
}

/** Geometry represents time, not an arbitrary action-button size. */
export function TimelineButton({left,extent,top,...props}:Omit<Props,'variant'|'style'>&{left:number;extent:number;top:number}){
 return <Button {...props} variant="navigation" data-layout="timeline" style={{left,width:extent,top}}/>;
}
