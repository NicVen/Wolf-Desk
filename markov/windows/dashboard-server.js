// Markov Trading Dashboard — local server (port 3001)
import express from "express";
import https   from "https";
import fs       from "fs";
import path     from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT      = 3001;
const POS_FILE  = path.join(__dirname, "window-position.json");

// ── Pairs ─────────────────────────────────────────────────────────────────────
const PAIRS = [
  { symbol:"EURUSD",  yahoo:"EURUSD=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"GBPUSD",  yahoo:"GBPUSD=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"USDJPY",  yahoo:"USDJPY=X",  pip:0.01,   markovThr:0.010 },
  { symbol:"USDCHF",  yahoo:"USDCHF=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"AUDUSD",  yahoo:"AUDUSD=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"NZDUSD",  yahoo:"NZDUSD=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"USDCAD",  yahoo:"USDCAD=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"GBPJPY",  yahoo:"GBPJPY=X",  pip:0.01,   markovThr:0.010 },
  { symbol:"EURJPY",  yahoo:"EURJPY=X",  pip:0.01,   markovThr:0.010 },
  { symbol:"EURGBP",  yahoo:"EURGBP=X",  pip:0.0001, markovThr:0.010 },
  { symbol:"XAUUSD",  yahoo:"GC=F",      pip:0.1,    markovThr:0.015 },
  { symbol:"XAGUSD",  yahoo:"SI=F",      pip:0.001,  markovThr:0.020 },
  { symbol:"USOIL",   yahoo:"CL=F",      pip:0.01,   markovThr:0.020 },
  { symbol:"NAS100",  yahoo:"NQ=F",      pip:1.0,    markovThr:0.020 },
  { symbol:"SPX500",  yahoo:"ES=F",      pip:0.25,   markovThr:0.020 },
  { symbol:"US30",    yahoo:"YM=F",      pip:1.0,    markovThr:0.020 },
  { symbol:"BTCUSD",  yahoo:"BTC-USD",   pip:1.0,    markovThr:0.030 },
  { symbol:"ETHUSD",  yahoo:"ETH-USD",   pip:0.1,    markovThr:0.030 },
];

// ── Indicator math ────────────────────────────────────────────────────────────
function ema(closes, p) {
  const k = 2/(p+1); let v = closes[0];
  for (let i=1;i<closes.length;i++) v = closes[i]*k + v*(1-k);
  return v;
}
function rsi(closes, p=14) {
  if (closes.length < p+2) return 50;
  let g=0,l=0;
  for (let i=1;i<=p;i++){const d=closes[i]-closes[i-1]; d>0?g+=d:l-=d;}
  let ag=g/p,al=l/p;
  for (let i=p+1;i<closes.length;i++){
    const d=closes[i]-closes[i-1];
    ag=(ag*(p-1)+Math.max(d,0))/p; al=(al*(p-1)+Math.max(-d,0))/p;
  }
  return al===0?100:parseFloat((100-100/(1+ag/al)).toFixed(2));
}
function rsiSeries(closes, p=14) {
  if (closes.length<p+2) return [];
  const out=[]; let g=0,l=0;
  for (let i=1;i<=p;i++){const d=closes[i]-closes[i-1]; d>0?g+=d:l-=d;}
  let ag=g/p,al=l/p;
  out.push(al===0?100:parseFloat((100-100/(1+ag/al)).toFixed(2)));
  for (let i=p+1;i<closes.length;i++){
    const d=closes[i]-closes[i-1];
    ag=(ag*(p-1)+Math.max(d,0))/p; al=(al*(p-1)+Math.max(-d,0))/p;
    out.push(al===0?100:parseFloat((100-100/(1+ag/al)).toFixed(2)));
  }
  return out;
}
function macdHistogram(closes) {
  if (closes.length<26) return 0;
  const k12=2/13,k26=2/27; let e12=closes[0],e26=closes[0];
  for (let i=1;i<closes.length;i++){e12=closes[i]*k12+e12*(1-k12); e26=closes[i]*k26+e26*(1-k26);}
  return parseFloat((e12-e26).toFixed(6));
}
function atr(bars,p=14) {
  if (bars.length<p+1) return 0;
  const trs=bars.slice(1).map((b,i)=>Math.max(b.high-b.low,Math.abs(b.high-bars[i].close),Math.abs(b.low-bars[i].close)));
  return trs.slice(-p).reduce((a,b)=>a+b,0)/p;
}
function adx(bars,p=14) {
  if (bars.length<p*2+1) return 0;
  const trs=[],pdms=[],ndms=[];
  for (let i=1;i<bars.length;i++){
    trs.push(Math.max(bars[i].high-bars[i].low,Math.abs(bars[i].high-bars[i-1].close),Math.abs(bars[i].low-bars[i-1].close)));
    const up=bars[i].high-bars[i-1].high,dn=bars[i-1].low-bars[i].low;
    pdms.push(up>dn&&up>0?up:0); ndms.push(dn>up&&dn>0?dn:0);
  }
  let atrW=trs.slice(0,p).reduce((a,b)=>a+b,0),pdmW=pdms.slice(0,p).reduce((a,b)=>a+b,0),ndmW=ndms.slice(0,p).reduce((a,b)=>a+b,0);
  const dxs=[];
  for (let i=p;i<trs.length;i++){
    atrW=atrW-atrW/p+trs[i]; pdmW=pdmW-pdmW/p+pdms[i]; ndmW=ndmW-ndmW/p+ndms[i];
    const pdi=atrW>0?100*pdmW/atrW:0,ndi=atrW>0?100*ndmW/atrW:0;
    dxs.push((pdi+ndi)>0?100*Math.abs(pdi-ndi)/(pdi+ndi):0);
  }
  if (dxs.length<p) return 0;
  let adxV=dxs.slice(0,p).reduce((a,b)=>a+b,0)/p;
  for (let i=p;i<dxs.length;i++) adxV=(adxV*(p-1)+dxs[i])/p;
  return parseFloat(adxV.toFixed(2));
}
function structure(bars) {
  const highs=[],lows=[];
  for (let i=2;i<bars.length-2;i++){
    if (bars[i].high>bars[i-1].high&&bars[i].high>bars[i-2].high&&bars[i].high>bars[i+1].high&&bars[i].high>bars[i+2].high) highs.push(bars[i].high);
    if (bars[i].low<bars[i-1].low&&bars[i].low<bars[i-2].low&&bars[i].low<bars[i+1].low&&bars[i].low<bars[i+2].low) lows.push(bars[i].low);
  }
  const h=highs.slice(-3),l=lows.slice(-3);
  if (h.length>=2&&l.length>=2){
    if (h[h.length-1]>h[h.length-2]&&l[l.length-1]>l[l.length-2]) return "Uptrend";
    if (h[h.length-1]<h[h.length-2]&&l[l.length-1]<l[l.length-2]) return "Downtrend";
  }
  return "Ranging";
}
function srLevels(bars) {
  const tol=(Math.max(...bars.map(b=>b.high))-Math.min(...bars.map(b=>b.low)))*0.002,lvs=[];
  for (let i=2;i<bars.length-2;i++){
    if (bars[i].high>bars[i-1].high&&bars[i].high>bars[i+1].high){const ex=lvs.find(l=>Math.abs(l.price-bars[i].high)<tol);ex?ex.touches++:lvs.push({price:parseFloat(bars[i].high.toFixed(5)),type:"R",touches:1});}
    if (bars[i].low<bars[i-1].low&&bars[i].low<bars[i+1].low){const ex=lvs.find(l=>Math.abs(l.price-bars[i].low)<tol);ex?ex.touches++:lvs.push({price:parseFloat(bars[i].low.toFixed(5)),type:"S",touches:1});}
  }
  return lvs.sort((a,b)=>b.touches-a.touches).slice(0,8);
}
function patterns(bars) {
  const out={bull:0,bear:0,list:[]};
  if (bars.length<4) return out;
  const [b2,b1,b0]=bars.slice(-3);
  const body=Math.abs(b0.close-b0.open),range=b0.high-b0.low||0.00001;
  const uw=b0.high-Math.max(b0.open,b0.close),lw=Math.min(b0.open,b0.close)-b0.low;
  if (lw>body*2&&lw>uw*2){out.bull+=2;out.list.push("Pin Bar");}
  if (uw>body*2&&uw>lw*2){out.bear+=2;out.list.push("Bearish Pin");}
  if (b1.close<b1.open&&b0.close>b0.open&&b0.close>b1.open&&b0.open<b1.close){out.bull+=2;out.list.push("Bull Engulf");}
  if (b1.close>b1.open&&b0.close<b0.open&&b0.close<b1.open&&b0.open>b1.close){out.bear+=2;out.list.push("Bear Engulf");}
  if (body<range*0.1) out.list.push("Doji");
  if (b2.close<b2.open&&body/range<0.3&&b0.close>b0.open&&b0.close>(b2.open+b2.close)/2){out.bull+=2;out.list.push("Morning Star");}
  if (b2.close>b2.open&&body/range<0.3&&b0.close<b0.open&&b0.close<(b2.open+b2.close)/2){out.bear+=2;out.list.push("Evening Star");}
  return out;
}
function rsidiv(closes) {
  if (closes.length<60) return {type:"None",strength:0};
  const rs=rsiSeries(closes); if (rs.length<40) return {type:"None",strength:0};
  const px=closes.slice(-40),rv=rs.slice(-40);
  const [p1,p2]=[px.slice(5,15),px.slice(25,40)],[r1,r2]=[rv.slice(5,15),rv.slice(25,40)];
  const p1lo=Math.min(...p1),p2lo=Math.min(...p2),r1lo=Math.min(...r1),r2lo=Math.min(...r2);
  const p1hi=Math.max(...p1),p2hi=Math.max(...p2),r1hi=Math.max(...r1),r2hi=Math.max(...r2);
  if (p2lo<p1lo*0.9995&&r2lo>r1lo+3) return {type:"Bullish",desc:"RSI Bull Divergence",strength:Math.min(3,Math.max(1,Math.round((r2lo-r1lo)/5)))};
  if (p2hi>p1hi*1.0005&&r2hi<r1hi-3) return {type:"Bearish",desc:"RSI Bear Divergence",strength:Math.min(3,Math.max(1,Math.round((r1hi-r2hi)/5)))};
  return {type:"None",strength:0};
}
function sweep(bars,lvs) {
  if (bars.length<3||!lvs.length) return {detected:false};
  const last=bars[bars.length-1];
  for (const lv of lvs){
    if (lv.type==="S"&&last.low<lv.price&&last.close>lv.price&&last.close>last.open) return {detected:true,direction:"Bullish",desc:`Sweep S ${lv.price.toFixed(5)}`};
    if (lv.type==="R"&&last.high>lv.price&&last.close<lv.price&&last.close<last.open) return {detected:true,direction:"Bearish",desc:`Sweep R ${lv.price.toFixed(5)}`};
  }
  return {detected:false};
}
function volumeSignal(bars) {
  const vols=bars.map(b=>b.volume||0).filter(v=>v>0);
  if (vols.length<5) return {signal:"N/A",ratio:1};
  const avg=vols.slice(-20).reduce((a,b)=>a+b,0)/Math.min(vols.length,20);
  const ratio=parseFloat((vols[vols.length-1]/avg).toFixed(2));
  return {signal:ratio>=2?"SPIKE":ratio>=1.4?"HIGH":ratio>=0.7?"NORMAL":"LOW",ratio};
}

// ── Markov ────────────────────────────────────────────────────────────────────
function _matMul(A,B){
  const n=A.length,C=Array.from({length:n},()=>new Array(n).fill(0));
  for(let i=0;i<n;i++) for(let k=0;k<n;k++) for(let j=0;j<n;j++) C[i][j]+=A[i][k]*B[k][j];
  return C;
}
function _matPow(P,n){
  if(n<=1) return P;
  if(n%2===0){const h=_matPow(P,n/2);return _matMul(h,h);}
  return _matMul(P,_matPow(P,n-1));
}
function markovRegimes(closes,window=20,threshold=0.015){
  if(closes.length<window+15) return null;
  const labels=[];
  for(let i=1;i<closes.length;i++){
    if(i<window){labels.push(0);continue;}
    let roll=0;
    for(let j=i-window+1;j<=i;j++) roll+=Math.log(closes[j]/closes[j-1]);
    labels.push(roll>threshold?1:roll<-threshold?2:0);
  }
  const cnt=[[0,0,0],[0,0,0],[0,0,0]];
  for(let i=0;i<labels.length-1;i++) cnt[labels[i]][labels[i+1]]++;
  const P=cnt.map(row=>{const s=row.reduce((a,b)=>a+b,0);return s>0?row.map(v=>v/s):[1/3,1/3,1/3];});
  const cur=labels[labels.length-1];
  const conviction=parseFloat((P[cur][1]-P[cur][2]).toFixed(3));
  const P3=_matPow(P,3),P5=_matPow(P,5);
  let pi=[1/3,1/3,1/3];
  for(let k=0;k<80;k++){const next=[0,0,0];for(let j=0;j<3;j++) for(let i=0;i<3;i++) next[j]+=pi[i]*P[i][j];pi=next;}
  return{
    regime:["Sideways","Bull","Bear"][cur],regimeIdx:cur,conviction,
    persistence:parseFloat(P[cur][cur].toFixed(3)),
    forecast3:{bull:parseFloat(P3[cur][1].toFixed(3)),bear:parseFloat(P3[cur][2].toFixed(3))},
    forecast5:{bull:parseFloat(P5[cur][1].toFixed(3)),bear:parseFloat(P5[cur][2].toFixed(3))},
    stationary:{side:parseFloat(pi[0].toFixed(3)),bull:parseFloat(pi[1].toFixed(3)),bear:parseFloat(pi[2].toFixed(3))},
    matrix:P
  };
}

// ── Fetch ─────────────────────────────────────────────────────────────────────
function yahooFetch(symbol,interval,range){
  return new Promise((resolve,reject)=>{
    const url=`https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}`;
    const req=https.get(url,{headers:{"User-Agent":"Mozilla/5.0"}},(res)=>{
      let data="";
      res.on("data",c=>data+=c);
      res.on("end",()=>{
        try{
          const j=JSON.parse(data)?.chart?.result?.[0];
          if(!j){reject(new Error("No data"));return;}
          const q=j.indicators.quote[0],bars=[];
          for(let i=0;i<j.timestamp.length;i++) if(q.close[i]!=null) bars.push({open:q.open[i],high:q.high[i],low:q.low[i],close:q.close[i],volume:q.volume?.[i]||0});
          resolve(bars);
        }catch(e){reject(e);}
      });
    });
    req.on("error",reject);
    req.setTimeout(12000,()=>{req.destroy();reject(new Error("Timeout"));});
  });
}
async function fetchPair(pair){
  const[bars1h,barsD,barsW]=await Promise.all([
    yahooFetch(pair.yahoo,"1h","1mo"),
    yahooFetch(pair.yahoo,"1d","12mo"),
    yahooFetch(pair.yahoo,"1wk","5y").catch(()=>[]),
  ]);
  return{bars1h,barsD,barsW};
}

// ── Analyze ───────────────────────────────────────────────────────────────────
function analyze(symbol,bars,dailyBars,pip,markovThr=0.015){
  if(!bars||bars.length<50) return null;
  const closes=bars.map(b=>b.close),price=parseFloat(closes[closes.length-1].toFixed(5));
  const RSI=rsi(closes),EMA50=parseFloat(ema(closes,50).toFixed(5)),EMA200=parseFloat(ema(closes,200).toFixed(5));
  const MACD=macdHistogram(closes),ATR=atr(bars),ADX=adx(bars);
  const TREND=structure(bars),LEVELS=srLevels(bars),PAT=patterns(bars);
  const DIV=rsidiv(closes),SWEEP=sweep(bars,LEVELS),VOL=volumeSignal(bars);
  let daily=null;
  if(dailyBars&&dailyBars.length>50){
    const dc=dailyBars.map(b=>b.close),dp=dc[dc.length-1];
    const d50=ema(dc,50),d200=dc.length>=200?ema(dc,200):null,dt=structure(dailyBars);
    let db=0,dr=0;
    if(dp>d50)db+=2;else dr+=2;
    if(d200){dp>d200?db+=3:dr+=3;}
    if(dt==="Uptrend")db+=3;if(dt==="Downtrend")dr+=3;
    daily={bias:db>dr?"BULLISH":dr>db?"BEARISH":"NEUTRAL",trend:dt};
  }
  const markov=dailyBars&&dailyBars.length>50?markovRegimes(dailyBars.map(b=>b.close),20,markovThr):null;
  const nearS=LEVELS.filter(l=>l.type==="S"&&l.price<price).sort((a,b)=>b.price-a.price)[0];
  const nearR=LEVELS.filter(l=>l.type==="R"&&l.price>price).sort((a,b)=>a.price-b.price)[0];
  let bull=0,bear=0;
  if(RSI>60&&RSI<=70)bull+=2;else if(RSI<40&&RSI>=30)bear+=2;
  if(RSI>70)bull++;if(RSI<30)bear++;
  if(EMA50>EMA200)bull++;else bear++;
  if(price>EMA50)bull++;else bear++;
  if(price>EMA200)bull+=2;else bear+=2;
  if(price>EMA50&&EMA50>EMA200)bull+=2;else if(price<EMA50&&EMA50<EMA200)bear+=2;
  if(TREND==="Uptrend")bull+=3;if(TREND==="Downtrend")bear+=3;
  if(MACD>0)bull+=2;else bear+=2;
  if(daily){if(daily.bias==="BULLISH")bull+=3;else if(daily.bias==="BEARISH")bear+=3;}
  bull+=PAT.bull;bear+=PAT.bear;
  if(DIV.type==="Bullish")bull+=DIV.strength*2;if(DIV.type==="Bearish")bear+=DIV.strength*2;
  if(SWEEP.detected){SWEEP.direction==="Bullish"?bull+=3:bear+=3;}
  if(VOL.signal==="SPIKE"){bull>bear?bull+=2:bear+=2;}else if(VOL.signal==="HIGH"){bull>bear?bull++:bear++;}
  if(markov){if(markov.regimeIdx===1)bull+=3;else if(markov.regimeIdx===2)bear+=3;if(markov.conviction>0.5)bull+=2;else if(markov.conviction<-0.5)bear+=2;}
  const bias=bull>bear?"BULLISH":bear>bull?"BEARISH":"NEUTRAL";
  const rawDiff=Math.abs(bull-bear),ranging=ADX<20&&ADX>0;
  const mtfConflict=daily&&daily.bias!=="NEUTRAL"&&daily.bias!==bias&&bias!=="NEUTRAL";
  const markovConflict=markov&&markov.persistence>0.80&&((bias==="BULLISH"&&markov.regimeIdx===2)||(bias==="BEARISH"&&markov.regimeIdx===1));
  const conf=(ranging||mtfConflict||markovConflict)?"Low":rawDiff>=10?"High":rawDiff>=6?"Medium":"Low";
  let setup=null;
  if(bias!=="NEUTRAL"&&nearS&&nearR){
    let entry,sl,tp1,tp2,rr,pips1,pips2,pipsRisk;
    if(bias==="BULLISH"){
      entry=price;sl=parseFloat(Math.min(nearS.price-ATR*0.5,entry-ATR*2.0).toFixed(5));
      tp1=parseFloat((entry+(entry-sl)*2.0).toFixed(5));
      const tp2lv=LEVELS.filter(l=>l.type==="R"&&l.price>tp1).sort((a,b)=>a.price-b.price)[0];
      tp2=tp2lv?tp2lv.price:parseFloat((entry+(entry-sl)*2.5).toFixed(5));
      rr=entry-sl>0?parseFloat(((tp1-entry)/(entry-sl)).toFixed(2)):0;
      pips1=parseFloat(((tp1-entry)/pip).toFixed(1));pips2=parseFloat(((tp2-entry)/pip).toFixed(1));pipsRisk=parseFloat(((entry-sl)/pip).toFixed(1));
    }else{
      entry=price;sl=parseFloat(Math.max(nearR.price+ATR*0.5,entry+ATR*2.0).toFixed(5));
      tp1=parseFloat((entry-(sl-entry)*2.0).toFixed(5));
      const tp2lv=LEVELS.filter(l=>l.type==="S"&&l.price<tp1).sort((a,b)=>b.price-a.price)[0];
      tp2=tp2lv?tp2lv.price:parseFloat((entry-(sl-entry)*2.5).toFixed(5));
      rr=sl-entry>0?parseFloat(((entry-tp1)/(sl-entry)).toFixed(2)):0;
      pips1=parseFloat(((entry-tp1)/pip).toFixed(1));pips2=parseFloat(((entry-tp2)/pip).toFixed(1));pipsRisk=parseFloat(((sl-entry)/pip).toFixed(1));
    }
    let gate="";
    if(rr<1.5)gate=`R:R ${rr}:1 below minimum`;
    else if(ranging)gate=`Ranging (ADX ${ADX})`;
    else if(mtfConflict)gate=`MTF conflict - Daily ${daily.bias}`;
    else if(markovConflict)gate=`Markov ${markov.regime} regime vs ${bias}`;
    else if(markov&&bias==="BULLISH"&&markov.forecast3.bear>0.55)gate=`3-bar forecast ${(markov.forecast3.bear*100).toFixed(0)}% Bear`;
    else if(markov&&bias==="BEARISH"&&markov.forecast3.bull>0.55)gate=`3-bar forecast ${(markov.forecast3.bull*100).toFixed(0)}% Bull`;
    else if(conf==="Low")gate=`Low confluence`;
    setup={direction:bias==="BULLISH"?"BUY":"SELL",entry,sl,tp1,tp2,rr,pips1,pips2,pipsRisk,quality:gate===""?"VALID":"FILTERED",gate};
  }
  return{symbol,price,RSI,EMA50,EMA200,MACD,ATR,ADX,TREND,bias,conf,bull,bear,ranging,mtfConflict,patterns:PAT.list,divergence:DIV.type!=="None"?DIV.desc:null,sweep:SWEEP.detected?SWEEP.desc:null,volume:VOL.signal,dailyBias:daily?daily.bias:"N/A",markov,nearS:nearS?nearS.price:null,nearR:nearR?nearR.price:null,setup,timeframe:"1H"};
}
function analyzeSwing(symbol,barsD,barsW,pip,markovThr=0.015){
  if(!barsD||barsD.length<60) return null;
  const closes=barsD.map(b=>b.close),price=closes[closes.length-1];
  const RSI=parseFloat(rsi(closes).toFixed(1)),EMA50=parseFloat(ema(closes,50).toFixed(5));
  const EMA200=closes.length>=200?parseFloat(ema(closes,200).toFixed(5)):EMA50;
  const MACD=parseFloat(macdHistogram(closes).toFixed(5)),ATR=parseFloat(atr(barsD,14).toFixed(5));
  const ADX=parseFloat(adx(barsD,14).toFixed(1)),TREND=structure(barsD),LEVELS=srLevels(barsD);
  const PAT=patterns(barsD),DIV=rsidiv(closes),SWEEP=sweep(barsD,LEVELS),VOL=volumeSignal(barsD);
  const markov=markovRegimes(closes,20,markovThr);
  let weekly=null;
  if(barsW&&barsW.length>20){
    const wc=barsW.map(b=>b.close),wp=wc[wc.length-1],w50=ema(wc,50),wt=structure(barsW);
    let wb=0,wr=0;if(wp>w50)wb+=3;else wr+=3;if(wt==="Uptrend")wb+=3;if(wt==="Downtrend")wr+=3;
    weekly={bias:wb>wr?"BULLISH":wr>wb?"BEARISH":"NEUTRAL"};
  }
  const nearS=LEVELS.filter(l=>l.type==="S"&&l.price<price).sort((a,b)=>b.price-a.price)[0];
  const nearR=LEVELS.filter(l=>l.type==="R"&&l.price>price).sort((a,b)=>a.price-b.price)[0];
  let bull=0,bear=0;
  if(RSI>60&&RSI<=70)bull+=2;else if(RSI<40&&RSI>=30)bear+=2;
  if(RSI>70)bull++;if(RSI<30)bear++;
  if(EMA50>EMA200)bull++;else bear++;
  if(price>EMA50)bull++;else bear++;
  if(price>EMA200)bull+=2;else bear+=2;
  if(price>EMA50&&EMA50>EMA200)bull+=2;else if(price<EMA50&&EMA50<EMA200)bear+=2;
  if(TREND==="Uptrend")bull+=3;if(TREND==="Downtrend")bear+=3;
  if(MACD>0)bull+=2;else bear+=2;
  if(weekly){if(weekly.bias==="BULLISH")bull+=3;else if(weekly.bias==="BEARISH")bear+=3;}
  bull+=PAT.bull;bear+=PAT.bear;
  if(DIV.type==="Bullish")bull+=DIV.strength*2;if(DIV.type==="Bearish")bear+=DIV.strength*2;
  if(SWEEP.detected){SWEEP.direction==="Bullish"?bull+=3:bear+=3;}
  if(VOL.signal==="SPIKE"){bull>bear?bull+=2:bear+=2;}else if(VOL.signal==="HIGH"){bull>bear?bull++:bear++;}
  if(markov){if(markov.regimeIdx===1)bull+=3;else if(markov.regimeIdx===2)bear+=3;if(markov.conviction>0.5)bull+=2;else if(markov.conviction<-0.5)bear+=2;}
  const bias=bull>bear?"BULLISH":bear>bull?"BEARISH":"NEUTRAL";
  const rawDiff=Math.abs(bull-bear),ranging=ADX<18&&ADX>0;
  const mtfConflict=weekly&&weekly.bias!=="NEUTRAL"&&weekly.bias!==bias&&bias!=="NEUTRAL";
  const markovConflict=markov&&markov.persistence>0.80&&((bias==="BULLISH"&&markov.regimeIdx===2)||(bias==="BEARISH"&&markov.regimeIdx===1));
  const conf=(ranging||mtfConflict||markovConflict)?"Low":rawDiff>=10?"High":rawDiff>=6?"Medium":"Low";
  let setup=null;
  if(bias!=="NEUTRAL"&&nearS&&nearR){
    let entry,sl,tp1,tp2,rr,pips1,pips2,pipsRisk;
    if(bias==="BULLISH"){
      entry=price;sl=parseFloat(Math.min(nearS.price-ATR*0.3,entry-ATR*1.5).toFixed(5));
      tp1=parseFloat((entry+(entry-sl)*2.0).toFixed(5));
      const tp2lv=LEVELS.filter(l=>l.type==="R"&&l.price>tp1).sort((a,b)=>a.price-b.price)[0];
      tp2=tp2lv?tp2lv.price:parseFloat((entry+(entry-sl)*3.0).toFixed(5));
      rr=entry-sl>0?parseFloat(((tp1-entry)/(entry-sl)).toFixed(2)):0;
      pips1=parseFloat(((tp1-entry)/pip).toFixed(1));pips2=parseFloat(((tp2-entry)/pip).toFixed(1));pipsRisk=parseFloat(((entry-sl)/pip).toFixed(1));
    }else{
      entry=price;sl=parseFloat(Math.max(nearR.price+ATR*0.3,entry+ATR*1.5).toFixed(5));
      tp1=parseFloat((entry-(sl-entry)*2.0).toFixed(5));
      const tp2lv=LEVELS.filter(l=>l.type==="S"&&l.price<tp1).sort((a,b)=>b.price-a.price)[0];
      tp2=tp2lv?tp2lv.price:parseFloat((entry-(sl-entry)*3.0).toFixed(5));
      rr=sl-entry>0?parseFloat(((entry-tp1)/(sl-entry)).toFixed(2)):0;
      pips1=parseFloat(((entry-tp1)/pip).toFixed(1));pips2=parseFloat(((entry-tp2)/pip).toFixed(1));pipsRisk=parseFloat(((sl-entry)/pip).toFixed(1));
    }
    let gate="";
    if(rr<1.5)gate=`R:R ${rr}:1 below minimum`;
    else if(ranging)gate=`Ranging (ADX ${ADX})`;
    else if(mtfConflict)gate=`MTF conflict`;
    else if(markovConflict)gate=`Markov ${markov.regime} vs ${bias}`;
    else if(markov&&bias==="BULLISH"&&markov.forecast3.bear>0.55)gate=`Forecast ${(markov.forecast3.bear*100).toFixed(0)}% Bear`;
    else if(markov&&bias==="BEARISH"&&markov.forecast3.bull>0.55)gate=`Forecast ${(markov.forecast3.bull*100).toFixed(0)}% Bull`;
    else if(conf==="Low")gate=`Low confluence`;
    setup={direction:bias==="BULLISH"?"BUY":"SELL",entry,sl,tp1,tp2,rr,pips1,pips2,pipsRisk,quality:gate===""?"VALID":"FILTERED",gate};
  }
  return{symbol,price:parseFloat(price.toFixed(5)),RSI,EMA50,EMA200,MACD,ATR,ADX,TREND,bias,conf,bull,bear,ranging,mtfConflict,patterns:PAT.list,divergence:DIV.type!=="None"?DIV.desc:null,sweep:SWEEP.detected?SWEEP.desc:null,volume:VOL.signal,dailyBias:weekly?weekly.bias:"N/A",markov,nearS:nearS?nearS.price:null,nearR:nearR?nearR.price:null,setup,timeframe:"SWING"};
}

// ── State + scanner ───────────────────────────────────────────────────────────
const state = { results:[], scanning:false, lastScan:null, progress:0, total:PAIRS.length*2 };

async function runScan() {
  if (state.scanning) return;
  state.scanning = true; state.progress = 0;
  const results = [];
  for (const pair of PAIRS) {
    try {
      const { bars1h, barsD, barsW } = await fetchPair(pair);
      const r1 = analyze(pair.symbol, bars1h, barsD, pair.pip, pair.markovThr||0.015);
      if (r1) results.push(r1);
      state.progress++;
      const sw = analyzeSwing(pair.symbol, barsD, barsW, pair.pip, pair.markovThr||0.015);
      if (sw) results.push(sw);
      state.progress++;
    } catch(e) { state.progress += 2; }
  }
  state.results = results;
  state.lastScan = Date.now();
  state.scanning = false;
}

// ── Express ───────────────────────────────────────────────────────────────────
const app = express();
app.use(express.json());

app.get("/api/status", (req, res) => res.json({
  scanning: state.scanning, lastScan: state.lastScan,
  progress: state.progress, total: state.total,
  count: state.results.length
}));
app.get("/api/results", (req, res) => res.json({
  scanning: state.scanning, lastScan: state.lastScan,
  progress: state.progress, total: state.total,
  results: state.results
}));
app.post("/api/scan", (req, res) => {
  res.json({ ok: true });
  runScan();
});
app.get("/api/position", (req, res) => {
  try { res.json(JSON.parse(fs.readFileSync(POS_FILE,"utf8"))); }
  catch { res.json({ x:null, y:null, w:460, h:800 }); }
});
app.post("/api/position", (req, res) => {
  fs.writeFileSync(POS_FILE, JSON.stringify(req.body));
  res.json({ ok: true });
});

// ── Dashboard HTML ────────────────────────────────────────────────────────────
app.get("/", (req, res) => res.send(`<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><title>Markov Dashboard</title>
<style>
*{box-sizing:border-box;margin:0;padding:0;}
:root{--bg:#0B0F0D;--bg2:#0F1511;--card:#121A15;--border:#1A2620;
  --green:#3FDE7E;--bull:#84BBA1;--bear:#C57F86;--side:#A4ABB7;
  --text:#E8EDE9;--dim:#6B7570;--warn:#E8C87A;}
html,body{height:100%;overflow:hidden;}
body{background:var(--bg);color:var(--text);font-family:'Consolas','Courier New',monospace;font-size:12px;display:flex;flex-direction:column;}

/* Header */
#hdr{background:var(--bg2);border-bottom:1px solid var(--border);padding:8px 10px;display:flex;align-items:center;gap:6px;flex-shrink:0;}
.dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);flex-shrink:0;}
.dot.off{background:#444;box-shadow:none;}
#title{font-size:11px;font-weight:bold;letter-spacing:2px;color:var(--green);flex:1;}
#btn-scan{background:var(--green);color:#0B0F0D;border:none;padding:4px 10px;font-family:inherit;font-size:10px;font-weight:bold;cursor:pointer;letter-spacing:1px;}
#btn-scan:disabled{background:#1A3A28;color:#2A5A38;cursor:not-allowed;}
#countdown{font-size:10px;color:var(--dim);min-width:38px;text-align:right;}
#progress-bar{height:2px;background:var(--border);flex-shrink:0;}
#progress-fill{height:2px;background:var(--green);width:0%;transition:width 0.5s;}

/* Summary bar */
#summary{background:var(--bg2);border-bottom:1px solid var(--border);padding:6px 10px;display:flex;gap:14px;flex-shrink:0;flex-wrap:wrap;}
.stat{display:flex;flex-direction:column;gap:1px;}
.stat-label{font-size:9px;color:var(--dim);letter-spacing:1px;}
.stat-val{font-size:13px;font-weight:bold;}
.v{color:var(--green)}.f{color:var(--warn)}.n{color:var(--dim)}
.bull{color:var(--bull)}.bear{color:var(--bear)}.side{color:var(--side)}

/* Scrollable body */
#body{flex:1;overflow-y:auto;overflow-x:hidden;}
#body::-webkit-scrollbar{width:4px;}
#body::-webkit-scrollbar-track{background:var(--bg);}
#body::-webkit-scrollbar-thumb{background:var(--border);}

/* Section headers */
.sec-hdr{padding:8px 10px 4px;font-size:9px;letter-spacing:2px;color:var(--dim);display:flex;justify-content:space-between;align-items:center;}
.sec-hdr span{cursor:pointer;color:var(--green);}

/* Setup card */
.card{margin:4px 8px;border-radius:2px;border:1px solid var(--border);background:var(--card);}
.card.valid{border-left:3px solid var(--green);}
.card.filtered{border-left:3px solid #2A3A2F;}
.card-hdr{display:flex;align-items:center;gap:6px;padding:6px 8px;border-bottom:1px solid var(--border);}
.pair-name{font-size:13px;font-weight:bold;color:var(--text);min-width:70px;}
.dir.buy{color:var(--bull);}.dir.sell{color:var(--bear);}
.tf{color:var(--dim);font-size:10px;}
.conf-badge{margin-left:auto;font-size:9px;padding:1px 5px;border-radius:1px;}
.conf-badge.High{background:#0E2A1A;color:var(--green);}
.conf-badge.Medium{background:#2A2A0E;color:var(--warn);}
.conf-badge.Low{background:#1A1A1A;color:var(--dim);}
.card-body{padding:5px 8px;display:grid;grid-template-columns:1fr 1fr;gap:2px 10px;}
.card-body.full{grid-template-columns:1fr;}
.kv{display:flex;justify-content:space-between;gap:4px;}
.k{color:var(--dim);white-space:nowrap;}.vv{text-align:right;white-space:nowrap;}
.regime-bar{grid-column:1/-1;display:flex;align-items:center;gap:6px;padding:3px 0;border-top:1px solid var(--border);margin-top:2px;}
.regime-label{font-size:10px;font-weight:bold;}
.regime-label.Bull{color:var(--bull)}.regime-label.Bear{color:var(--bear)}.regime-label.Sideways{color:var(--side)}
.conv{font-size:10px;color:var(--dim);}
.gate-text{grid-column:1/-1;color:#4A5A4F;font-size:10px;padding-top:2px;}

/* Pairs table */
#pairs-table{padding:0 8px 8px;}
.pair-row{display:grid;grid-template-columns:62px 62px 72px 46px 1fr;padding:3px 4px;border-radius:1px;gap:2px;}
.pair-row:hover{background:var(--bg2);}
.pair-row.row-hdr{color:var(--dim);font-size:9px;letter-spacing:1px;border-bottom:1px solid var(--border);padding-bottom:4px;margin-bottom:2px;}
.cell{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}

/* Footer / lock controls */
#footer{background:var(--bg2);border-top:1px solid var(--border);padding:6px 10px;flex-shrink:0;}
#lock-row{display:flex;align-items:center;gap:4px;margin-bottom:4px;}
.lock-label{font-size:9px;color:var(--dim);letter-spacing:1px;margin-right:2px;}
.lock-btn{background:var(--border);color:var(--dim);border:none;padding:3px 7px;font-family:inherit;font-size:9px;cursor:pointer;letter-spacing:1px;}
.lock-btn:hover{background:#222E27;color:var(--text);}
.lock-btn.active{background:#0E2A1A;color:var(--green);}
#last-scan-txt{font-size:9px;color:var(--dim);text-align:center;}
#spinner{display:inline-block;animation:spin 1s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
.empty-state{padding:30px 10px;text-align:center;color:var(--dim);}
</style></head>
<body>
<div id="hdr">
  <div class="dot" id="dot"></div>
  <div id="title">MARKOV DASHBOARD</div>
  <button id="btn-scan" onclick="triggerScan()">SCAN NOW</button>
  <div id="countdown">--:--</div>
</div>
<div id="progress-bar"><div id="progress-fill"></div></div>
<div id="summary"></div>
<div id="body">
  <div id="valid-section"></div>
  <div id="all-section"></div>
</div>
<div id="footer">
  <div id="lock-row">
    <span class="lock-label">LOCK:</span>
    <button class="lock-btn" onclick="lockPos('TL')">TOP-LEFT</button>
    <button class="lock-btn" onclick="lockPos('TR')">TOP-RIGHT</button>
    <button class="lock-btn" onclick="lockPos('BL')">BOT-LEFT</button>
    <button class="lock-btn" onclick="lockPos('BR')">BOT-RIGHT</button>
    <button class="lock-btn" onclick="lockPos('C')">HERE</button>
  </div>
  <div id="last-scan-txt">Loading...</div>
</div>

<script>
const W=460,H=800;
let cdTimer=null,pollTimer=null,savedPos=null,allOpen=true;

// ── Init ──────────────────────────────────────────────────────────────────────
async function init(){
  try{
    const pos=await fetch('/api/position').then(r=>r.json());
    if(pos.x!=null){ savedPos=pos; window.moveTo(pos.x,pos.y); window.resizeTo(pos.w||W,pos.h||H); }
    else window.resizeTo(W,H);
  }catch{}
  const data=await fetch('/api/results').then(r=>r.json());
  if(data.results&&data.results.length>0){ render(data); startCountdown(); }
  else triggerScan();
}

// ── Scan ──────────────────────────────────────────────────────────────────────
async function triggerScan(){
  if(pollTimer) clearInterval(pollTimer);
  document.getElementById('btn-scan').disabled=true;
  document.getElementById('dot').className='dot off';
  renderSummaryScanning();
  await fetch('/api/scan',{method:'POST'});
  pollTimer=setInterval(pollResults,1500);
}
async function pollResults(){
  const data=await fetch('/api/results').then(r=>r.json()).catch(()=>null);
  if(!data) return;
  const pct=data.total>0?Math.round(data.progress/data.total*100):0;
  document.getElementById('progress-fill').style.width=pct+'%';
  document.getElementById('last-scan-txt').textContent=
    data.scanning?'Scanning... '+data.progress+'/'+data.total+' pairs':'';
  if(!data.scanning){
    clearInterval(pollTimer); pollTimer=null;
    document.getElementById('progress-fill').style.width='100%';
    setTimeout(()=>document.getElementById('progress-fill').style.width='0%',800);
    document.getElementById('btn-scan').disabled=false;
    document.getElementById('dot').className='dot';
    render(data); startCountdown();
  }
}

// ── Countdown ─────────────────────────────────────────────────────────────────
function startCountdown(){
  if(cdTimer) clearInterval(cdTimer);
  let secs=15*60;
  const el=document.getElementById('countdown');
  cdTimer=setInterval(()=>{
    secs--;
    const m=Math.floor(secs/60),s=String(secs%60).padStart(2,'0');
    el.textContent=m+':'+s;
    if(secs<=0){ clearInterval(cdTimer); triggerScan(); }
  },1000);
}

// ── Render ────────────────────────────────────────────────────────────────────
function regimeColor(r){ return r==='Bull'?'bull':r==='Bear'?'bear':'side'; }
function biasColor(b){ return b==='BULLISH'?'bull':b==='BEARISH'?'bear':'side'; }
function fmt(v){ return v>=0?'+'+v:String(v); }

function render(data){
  const results=data.results||[];
  const valid=results.filter(r=>r.setup?.quality==='VALID');
  const filtered=results.filter(r=>r.setup?.quality==='FILTERED');
  const noSetup=results.filter(r=>!r.setup);
  const bulls=results.filter(r=>r.bias==='BULLISH').length;
  const bears=results.filter(r=>r.bias==='BEARISH').length;
  const sides=results.filter(r=>r.bias==='NEUTRAL').length;
  const regBull=results.filter(r=>r.markov?.regime==='Bull').length;
  const regBear=results.filter(r=>r.markov?.regime==='Bear').length;
  const regSide=results.filter(r=>r.markov?.regime==='Sideways').length;

  document.getElementById('summary').innerHTML=\`
    <div class="stat"><div class="stat-label">VALID</div><div class="stat-val v">\${valid.length}</div></div>
    <div class="stat"><div class="stat-label">FILTERED</div><div class="stat-val f">\${filtered.length}</div></div>
    <div class="stat"><div class="stat-label">NO SETUP</div><div class="stat-val n">\${noSetup.length}</div></div>
    <div class="stat" style="border-left:1px solid var(--border);padding-left:14px">
      <div class="stat-label">BIAS MIX</div>
      <div class="stat-val" style="font-size:11px">
        <span class="bull">\${bulls}B</span>/<span class="bear">\${bears}S</span>/<span class="side">\${sides}N</span>
      </div>
    </div>
    <div class="stat"><div class="stat-label">REGIME</div>
      <div class="stat-val" style="font-size:11px">
        <span class="bull">\${regBull}</span>/<span class="bear">\${regBear}</span>/<span class="side">\${regSide}</span>
      </div>
    </div>
  \`;

  // Valid cards
  let vhtml='<div class="sec-hdr"><span>VALID SETUPS (\${valid.length})</span></div>';
  vhtml='<div class="sec-hdr"><span>VALID SETUPS ('+valid.length+')</span></div>';
  if(valid.length===0) vhtml+='<div class="empty-state">No valid setups right now.<br>Market is waiting.</div>';
  for(const r of valid) vhtml+=cardHTML(r,true);

  // Filtered section
  if(filtered.length>0){
    vhtml+='<div class="sec-hdr"><span>FILTERED ('+filtered.length+')</span></div>';
    for(const r of filtered) vhtml+=cardHTML(r,false);
  }
  document.getElementById('valid-section').innerHTML=vhtml;

  // All pairs table
  let thtml='<div class="sec-hdr"><span>ALL PAIRS</span><span onclick="toggleAll()">'+( allOpen?'COLLAPSE':'EXPAND')+'</span></div>';
  thtml+='<div id="pairs-inner" style="display:'+(allOpen?'block':'none')+'">';
  thtml+='<div id="pairs-table"><div class="pair-row row-hdr"><div class="cell">PAIR</div><div class="cell">BIAS</div><div class="cell">REGIME</div><div class="cell">CONF</div><div class="cell">SETUP</div></div>';
  const deduped=[];
  const seen={};
  for(const r of results){
    const key=r.symbol+r.timeframe;
    if(!seen[key]){seen[key]=true;deduped.push(r);}
  }
  for(const r of deduped){
    const mkv=r.markov;
    const bc=biasColor(r.bias),rc=mkv?regimeColor(mkv.regime):'side';
    const setupTxt=r.setup?.quality==='VALID'?r.setup.direction+' '+r.setup.rr+':1':r.setup?.quality==='FILTERED'?'filtered':'--';
    const conv=mkv?fmt(mkv.conviction):'';
    thtml+=\`<div class="pair-row" title="\${r.timeframe}">
      <div class="cell">\${r.symbol} <span style="color:var(--dim);font-size:9px">\${r.timeframe==='SWING'?'SW':'1H'}</span></div>
      <div class="cell \${bc}">\${r.bias.slice(0,4)}</div>
      <div class="cell \${rc}">\${mkv?mkv.regime:'--'} <span style="color:var(--dim)">\${conv}</span></div>
      <div class="cell \${r.conf==='High'?'v':r.conf==='Medium'?'f':'n'}">\${r.conf}</div>
      <div class="cell \${r.setup?.quality==='VALID'?'v':r.setup?.quality==='FILTERED'?'f':'n'}">\${setupTxt}</div>
    </div>\`;
  }
  thtml+='</div></div>';
  document.getElementById('all-section').innerHTML=thtml;

  const ago=data.lastScan?Math.round((Date.now()-data.lastScan)/1000)+'s ago':'never';
  document.getElementById('last-scan-txt').textContent='Last scan: '+ago+' | '+results.length+' results | Auto-rescan in countdown above';
}

function cardHTML(r,isValid){
  const mkv=r.markov;
  const dir=r.setup?.direction||'';
  const rc=mkv?regimeColor(mkv.regime):'side';
  let h=\`<div class="card \${isValid?'valid':'filtered'}">
    <div class="card-hdr">
      <div class="pair-name">\${r.symbol}</div>
      <div class="dir \${dir.toLowerCase()}">\${dir}</div>
      <div class="tf">\${r.timeframe==='SWING'?'SWING':'1H'}</div>
      <div class="conf-badge \${r.conf}">\${r.conf.toUpperCase()}</div>
    </div>
    <div class="card-body">\`;
  if(r.setup&&isValid){
    h+=\`<div class="kv"><span class="k">Entry</span><span class="vv">\${r.setup.entry}</span></div>
      <div class="kv"><span class="k">R:R</span><span class="vv">\${r.setup.rr}:1</span></div>
      <div class="kv"><span class="k">SL</span><span class="vv">\${r.setup.sl} (-\${r.setup.pipsRisk}p)</span></div>
      <div class="kv"><span class="k">TP1</span><span class="vv">\${r.setup.tp1} (+\${r.setup.pips1}p)</span></div>
      <div class="kv"><span class="k">TP2</span><span class="vv">\${r.setup.tp2}</span></div>
      <div class="kv"><span class="k">ADX</span><span class="vv">\${r.ADX}</span></div>\`;
  }
  h+=\`<div class="kv"><span class="k">RSI</span><span class="vv">\${r.RSI}</span></div>
    <div class="kv"><span class="k">Daily</span><span class="vv \${biasColor(r.dailyBias)}">\${r.dailyBias}</span></div>
    <div class="kv"><span class="k">Trend</span><span class="vv">\${r.TREND}</span></div>
    <div class="kv"><span class="k">Vol</span><span class="vv">\${r.volume}</span></div>\`;
  if(mkv){
    const persist=Math.round(mkv.persistence*100);
    h+=\`<div class="regime-bar">
      <span class="regime-label \${mkv.regime}">\${mkv.regime.toUpperCase()}</span>
      <span class="conv">conv \${fmt(mkv.conviction)} &bull; persist \${persist}% &bull; F3: B\${Math.round(mkv.forecast3.bull*100)}% S\${Math.round(mkv.forecast3.bear*100)}%</span>
    </div>\`;
  }
  if(r.setup&&!isValid&&r.setup.gate){
    h+=\`<div class="gate-text">FILTERED: \${r.setup.gate}</div>\`;
  }
  if(r.patterns&&r.patterns.length>0){
    h+=\`<div class="gate-text" style="color:var(--side)">\${r.patterns.join(', ')}</div>\`;
  }
  h+=\`</div></div>\`;
  return h;
}

function renderSummaryScanning(){
  document.getElementById('summary').innerHTML=\`
    <div class="stat"><div class="stat-label">STATUS</div>
      <div class="stat-val" style="color:var(--warn)">
        <span id="spinner">&#9696;</span> SCANNING
      </div>
    </div>
    <div class="stat"><div class="stat-label">PAIRS</div><div class="stat-val n">18</div></div>
  \`;
}
function toggleAll(){
  allOpen=!allOpen;
  const el=document.getElementById('pairs-inner');
  if(el) el.style.display=allOpen?'block':'none';
}

// ── Lock position ─────────────────────────────────────────────────────────────
async function lockPos(pos){
  const sw=screen.width,sh=screen.height,w=W,h=H;
  let x,y;
  if(pos==='TL'){x=10;y=10;}
  else if(pos==='TR'){x=sw-w-10;y=10;}
  else if(pos==='BL'){x=10;y=sh-h-50;}
  else if(pos==='BR'){x=sw-w-10;y=sh-h-50;}
  else{x=window.screenX;y=window.screenY;}
  window.moveTo(x,y);
  window.resizeTo(w,h);
  document.querySelectorAll('.lock-btn').forEach(b=>b.classList.remove('active'));
  event.target.classList.add('active');
  await fetch('/api/position',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y,w,h,pos})});
}

init();
</script></body></html>`));

app.listen(PORT, () => {
  console.log(`Markov Dashboard running at http://localhost:${PORT}`);
  runScan();
});
