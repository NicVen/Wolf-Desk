//+------------------------------------------------------------------+
//|  LicenseCheck.mqh — STAALWAG activation-code check for EAs/indics  |
//|                                                                    |
//|  Gates an EA/indicator on a live subscription. The client enters   |
//|  their activation key; this calls the licensing server, which      |
//|  answers valid/invalid based on whether they've paid. Access is    |
//|  removed automatically ~4h after a missed renewal (server-side).   |
//|                                                                    |
//|  SETUP (once per MT5 terminal):                                    |
//|    Tools > Options > Expert Advisors > "Allow WebRequest for       |
//|    listed URL" and add:  https://pay.178.104.88.38.sslip.io        |
//|                                                                    |
//|  USAGE in your EA:                                                 |
//|    #include <LicenseCheck.mqh>                                     |
//|    input string LicenseKey = "";     // client pastes their key    |
//|    int OnInit(){ if(!LicenseOK(LicenseKey,"GOLD")) return(INIT_FAILED); ... }
//|    void OnTick(){ if(!LicenseOK(LicenseKey,"GOLD")) return; ... }   |
//+------------------------------------------------------------------+
#property strict

#define LIC_BASE      "https://pay.178.104.88.38.sslip.io"
#define LIC_RECHECK   21600     // re-verify at most every 6h
#define LIC_OFFLINE   43200     // if server unreachable, trust last OK for 12h then block

// cache
datetime _lic_last_check = 0;
bool     _lic_last_ok    = false;
datetime _lic_last_ok_at = 0;

//+------------------------------------------------------------------+
bool _LicHttp(string url, string &out)
{
   char post[], result[];
   string headers = "";
   ResetLastError();
   int timeout = 8000;
   int code = WebRequest("GET", url, headers, timeout, post, result, headers);
   if(code == -1)
   {
      PrintFormat("License: WebRequest failed (err %d). Add %s to allowed URLs in "
                  "Tools>Options>Expert Advisors.", GetLastError(), LIC_BASE);
      return(false);
   }
   out = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   return(code == 200);
}

//+------------------------------------------------------------------+
//| Returns true while the license is paid/valid. Caches + fails      |
//| safely: brief offline grace, then blocks.                         |
//+------------------------------------------------------------------+
bool LicenseOK(string key, string product)
{
   if(StringLen(key) < 4)
   {
      Print("License: no activation key set. Enter your key in the inputs.");
      return(false);
   }

   datetime nowt = TimeCurrent();
   if(_lic_last_check > 0 && (nowt - _lic_last_check) < LIC_RECHECK)
      return(_lic_last_ok);   // within recheck window -> use cached answer

   string account = IntegerToString((int)AccountInfoInteger(ACCOUNT_LOGIN));
   string machine = AccountInfoString(ACCOUNT_SERVER);
   string url = LIC_BASE + "/verify?key=" + key +
                "&account=" + account +
                "&machine=" + machine +
                "&product=" + product;

   string body;
   bool http_ok = _LicHttp(url, body);

   if(!http_ok && StringFind(body, "\"valid\"") < 0)
   {
      // server unreachable — allow a short offline grace off the last good check
      if(_lic_last_ok && (nowt - _lic_last_ok_at) < LIC_OFFLINE)
      {
         Print("License: server unreachable, using offline grace.");
         return(true);
      }
      Print("License: server unreachable and offline grace expired — blocking.");
      _lic_last_ok = false;
      return(false);
   }

   _lic_last_check = nowt;
   bool ok = (StringFind(body, "\"valid\":true") >= 0);
   _lic_last_ok = ok;
   if(ok) _lic_last_ok_at = nowt;
   else   PrintFormat("License: not valid (%s). Response: %s", product, body);
   return(ok);
}
