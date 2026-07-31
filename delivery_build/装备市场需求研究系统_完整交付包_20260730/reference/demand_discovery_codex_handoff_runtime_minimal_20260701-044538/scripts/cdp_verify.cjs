const http=require('http');const net=require('net');const crypto=require('crypto');
const PORT=9334;
function get(path){return new Promise((res,rej)=>{http.get({host:'127.0.0.1',port:PORT,path},r=>{let d='';r.on('data',c=>d+=c);r.on('end',()=>res(d));}).on('error',rej);});}
function wsConnect(url){return new Promise((resolve,reject)=>{
 const u=new URL(url);const key=crypto.randomBytes(16).toString('base64');
 const sock=net.connect(u.port,u.hostname,()=>{sock.write(`GET ${u.pathname}${u.search} HTTP/1.1\r\nHost:${u.host}\r\nUpgrade:websocket\r\nConnection:Upgrade\r\nSec-WebSocket-Key:${key}\r\nSec-WebSocket-Version:13\r\n\r\n`);});
 let buf=Buffer.alloc(0);let handlers=[];let ready=false;
 function parse(){while(buf.length>=2){let len=buf[1]&127;let off=2;if(len===126){len=buf.readUInt16BE(2);off=4;}else if(len===127){len=Number(buf.readBigUInt64BE(2));off=10;}if(buf.length<off+len)return;const payload=buf.slice(off,off+len).toString();buf=buf.slice(off+len);handlers.forEach(h=>h(payload));}}
 sock.on('data',d=>{if(!ready){const s=d.indexOf('\r\n\r\n');if(s>=0){ready=true;buf=d.slice(s+4);resolve(api);parse();}}else{buf=Buffer.concat([buf,d]);parse();}});
 sock.on('error',reject);
 function send(obj){const data=Buffer.from(JSON.stringify(obj));const len=data.length;let header;if(len<126){header=Buffer.from([0x81,0x80|len]);}else{header=Buffer.alloc(8);header[0]=0x81;header[1]=0x80|126;header.writeUInt16BE(len,2);}const mask=crypto.randomBytes(4);const masked=Buffer.from(data);for(let i=0;i<len;i++)masked[i]^=mask[i%4];sock.write(Buffer.concat([header,mask,masked]));}
 const api={send,onMessage:h=>handlers.push(h),close:()=>sock.end()};
});}
(async()=>{
 const tabs=JSON.parse(await get('/json'));
 let tab=tabs.find(t=>t.type==='page'&&t.url.indexOf('localhost:8765')>=0)||tabs.find(t=>t.type==='page');
 const ws=await wsConnect(tab.webSocketDebuggerUrl);
 let id=0;const pend={};
 ws.onMessage(m=>{const o=JSON.parse(m);if(o.id&&pend[o.id])pend[o.id](o);});
 function cmd(method,params){return new Promise(r=>{const i=++id;pend[i]=r;ws.send({id:i,method,params:params||{}});});}
 await cmd('Page.enable');await cmd('Runtime.enable');
 await cmd('Runtime.evaluate',{expression:`location.hash='#evidence'`});
 await new Promise(r=>setTimeout(r,1500));
 const r=await cmd('Runtime.evaluate',{expression:`(function(){var n=document.querySelector('.node[data-id="n-tech2"]');if(!n)return 'no-node';n.click();var d=document.querySelector('.detail');return 'detail='+(!!d)+';dimmed='+document.querySelectorAll('.node.is-dim').length+';title='+(d?d.querySelector('.detail__title').textContent:'');})()`,returnByValue:true});
 console.log('NODE_CLICK:',r.result&&r.result.value);
 await new Promise(r=>setTimeout(r,400));
 let shot=await cmd('Page.captureScreenshot',{format:'png'});
 require('fs').writeFileSync('D:/amyproject/knowledgegraph/docs/frontend/_verify/evidence-node-detail.png',Buffer.from(shot.result.data,'base64'));
 // edge geometry check: ensure edges anchor near node centers
 const g=await cmd('Runtime.evaluate',{expression:`(function(){
   function c(id){var n=document.querySelector('.node[data-id="'+id+'"]');var w=document.querySelector('.canvas-wrap').getBoundingClientRect();var r=n.getBoundingClientRect();return {x:r.left-w.left+r.width/2,y:r.top-w.top+r.height/2};}
   var edges=document.querySelectorAll('path[data-edge]');var bad=0;
   edges.forEach(function(p){var a=c(p.dataset.from),b=c(p.dataset.to);var d=p.getAttribute('d');var m=d.match(/M([\\d.]+) ([\\d.]+).*?([\\d.]+) ([\\d.]+)$/);});
   return 'edgeCount='+edges.length;
 })()`,returnByValue:true});
 console.log('EDGE_GEOM:',g.result&&g.result.value);
 ws.close();process.exit(0);
})().catch(e=>{console.error('ERR',e.message);process.exit(1);});
