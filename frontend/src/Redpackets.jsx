import React,{useState} from 'react';
const money=n=>(n/100).toFixed(2);
const date=n=>new Date(n*1000).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai'});
export default function Redpackets({user}){
 const [filter,setFilter]=useState('valid');
 const now=user.serverTime??Math.floor(Date.now()/1000);
 const packets=user.orders.filter(o=>o.status==='SUCCESS'&&o.packet_id&&o.expires);
 const valid=packets.filter(o=>o.expires>now),expired=packets.filter(o=>o.expires<=now);
 const visible=filter==='valid'?valid:filter==='expired'?expired:packets;
 return <section className="panel redpackets" id="my-redpackets" aria-label="我的红包"><div className="section-title"><span className="number">02</span><h2>我的红包</h2><span className="muted">有效 {valid.length} 个 · 合计 ¥{money(user.redpacketBalance)}</span></div><div className="packet-tabs" role="group" aria-label="红包筛选">{[['valid','有效红包',valid.length],['expired','已过期',expired.length],['all','全部',packets.length]].map(([key,label,count])=><button key={key} aria-pressed={filter===key} onClick={()=>setFilter(key)}>{label} <span>{count}</span></button>)}</div><p className="packet-description">展示兑换成功的消费红包，发放后 7 天内有效。当前演示支持发放与查看，尚未接入消费核销。</p>{visible.length?<div className="packet-grid">{visible.map(o=>{const active=o.expires>now;return <article key={o.id} className={'voucher '+(active?'':'voucher-expired')} aria-label={'红包 '+o.packet_id}><div className="voucher-main"><div><span className="voucher-name">消费红包</span><strong><small>¥</small>{money(o.amount)}</strong></div><span className={'status '+(active?'SUCCESS':'expired')}>{active?'有效':'已过期'}</span></div><div className="voucher-times"><p>发放时间 <span>{date(o.expires-7*86400)}</span></p><p>到期时间 <span>{date(o.expires)}</span></p></div><details><summary>查看红包与兑换编号</summary><dl><dt>红包编号</dt><dd>{o.packet_id}</dd><dt>兑换订单</dt><dd>{o.id}</dd></dl></details></article>})}</div>:<div className="empty">{filter==='expired'?'暂无已过期红包':filter==='all'?'还没有红包，兑换成功后会自动显示在这里。':'暂无有效红包，兑换金币领取第一份消费红包。'}</div>}</section>
}
