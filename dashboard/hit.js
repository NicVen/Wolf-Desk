// Anonymous page counter for staalwag.com (no cookies, no IP kept, no personal data).
// Sends: page name, the browser's time zone (-> country only), and Play button taps.
(function(){
  function tz(){ try{ return Intl.DateTimeFormat().resolvedOptions().timeZone||""; }catch(e){ return ""; } }
  function send(e,k){
    var b=JSON.stringify({e:e,k:k,tz:tz()});
    try{ if(navigator.sendBeacon && navigator.sendBeacon("/hit", new Blob([b],{type:"text/plain"}))) return; }catch(x){}
    try{ fetch("/hit",{method:"POST",body:b,keepalive:true}); }catch(x){}
  }
  var page=(location.pathname.replace(/^\/+|\/+$/g,"")||"home");
  send("view",page);
  document.addEventListener("click",function(ev){
    var a=ev.target && ev.target.closest ? ev.target.closest('a[href^="/play"]') : null;
    if(a) send("play",page);
  },true);
})();
