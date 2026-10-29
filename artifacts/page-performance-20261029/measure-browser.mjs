import { chromium } from '/Users/wangchen/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.mjs'
import fs from 'node:fs/promises'
const label = process.argv[2] || 'before'
const url = process.argv[3] || 'https://www.deepquest.space/login'
const browser = await chromium.launch({headless:true, executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"})
const context = await browser.newContext({ viewport:{width:1440,height:1000} })
const page = await context.newPage()
const errors=[]
page.on('pageerror',e=>errors.push(e.message))
await page.addInitScript(()=>{window.__lcp=[];new PerformanceObserver(l=>window.__lcp.push(...l.getEntries().map(e=>({time:e.startTime,size:e.size,url:e.url})))).observe({type:'largest-contentful-paint',buffered:true})})
await page.goto(url,{waitUntil:'networkidle',timeout:60000})
await page.screenshot({path:`artifacts/page-performance-20261029/${label}.png`,fullPage:true})
const result=await page.evaluate(()=>({url:location.href,navigation:performance.getEntriesByType('navigation').map(e=>e.toJSON()),paints:performance.getEntriesByType('paint').map(e=>e.toJSON()),lcp:window.__lcp,resources:performance.getEntriesByType('resource').map(e=>({url:e.name,type:e.initiatorType,start:Math.round(e.startTime),duration:Math.round(e.duration),ttfb:Math.round(e.responseStart-e.requestStart),transfer:e.transferSize,decoded:e.decodedBodySize,protocol:e.nextHopProtocol}))}))
result.errors=errors
await fs.writeFile(`artifacts/page-performance-20261029/${label}.json`,JSON.stringify(result,null,2))
console.log(JSON.stringify({label,paints:result.paints,lcp:result.lcp,requests:result.resources.length,bytes:result.resources.reduce((a,e)=>a+e.transfer,0),errors,largest:result.resources.toSorted((a,b)=>b.transfer-a.transfer).slice(0,8),api:result.resources.filter(e=>e.url.includes('/api/'))},null,2))
await browser.close()
