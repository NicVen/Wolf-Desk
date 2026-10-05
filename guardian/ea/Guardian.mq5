//+------------------------------------------------------------------+
//| STAALWAG Guardian - your buddy over your shoulder                |
//|                                                                  |
//| Watches every trade and pending order on this MT5 account (also  |
//| the ones you place from your phone) and warns you when one could |
//| hurt the account: too big, too much open, no stop, big news, a   |
//| dead hour, or a prop-firm limit in reach.                        |
//|                                                                  |
//| It NEVER opens, changes or closes anything. No password leaves   |
//| this PC. The check runs on staalwag.com; if that can't be        |
//| reached, the basic size and stop checks still run here.          |
//|                                                                  |
//| Setup (once):                                                    |
//|  1. Tools > Options > Expert Advisors > tick "Allow WebRequest"  |
//|     and add  https://app.staalwag.com                            |
//|  2. Tools > Options > Notifications > tick "Enable Push" and     |
//|     paste your MetaQuotes ID (MT5 phone app > Settings > Chat    |
//|     and messages)                                                |
//|  3. Drag Guardian onto any one chart, put your key in Inputs.    |
//+------------------------------------------------------------------+
#property copyright "STAALWAG"
#property link      "https://staalwag.com"
#property version   "1.00"
#property description "Guardian watches your trades and warns you. It never trades."

input string GuardianKey    = "";     // Your STAALCALIBUR key (with Guardian)
input double RiskPercent    = 1.0;    // Your risk per trade (%)
input double ChallengeStart = 0;      // Prop challenge start size in $ (0 = no challenge)
input double DailyLossPct   = 5.0;    // Challenge daily loss limit (%)
input double MaxLossPct     = 10.0;   // Challenge max loss limit (%)
input int    GraceSeconds   = 5;      // Seconds to let you set a stop before checking
input bool   PushToPhone    = true;   // Send warnings to the MT5 app on your phone
input bool   PopupOnPC      = true;   // Pop-up warnings on this PC
input string ServerURL      = "https://app.staalwag.com/appguard/mt5";

ulong    g_seen[];       // tickets already judged (or open when Guardian started)
ulong    g_wait[];       // new tickets waiting out the grace period
datetime g_waitAt[];
bool     g_started = false;
bool     g_toldWeb = false, g_toldPush = false, g_toldKey = false;

//+------------------------------------------------------------------+
int OnInit()
  {
   if(StringLen(GuardianKey) < 4)
     {
      Alert("Guardian: put your STAALCALIBUR key in the Inputs tab.");
      return(INIT_PARAMETERS_INCORRECT);
     }
   EventSetTimer(1);
   string hello = StringFormat("Guardian is watching MT5 account %I64d. Open a trade and it checks it within seconds.",
                               AccountInfoInteger(ACCOUNT_LOGIN));
   Print(hello);
   if(PushToPhone && !SendNotification(hello))
      TellPushOff();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason) { EventKillTimer(); }

//+------------------------------------------------------------------+
int Find(const ulong &arr[], const ulong t)
  {
   for(int i = 0; i < ArraySize(arr); i++)
      if(arr[i] == t)
         return(i);
   return(-1);
  }

void Push(ulong &arr[], const ulong t)
  {
   int n = ArraySize(arr);
   ArrayResize(arr, n + 1);
   arr[n] = t;
  }

// Account-currency loss on 1.00 lot over a price distance, from the broker's own figures.
double PerLot(const string sym, const double dist)
  {
   double ts = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE_LOSS);
   if(tv <= 0)
      tv = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   if(ts <= 0 || tv <= 0)
      return(-1);
   return(dist / ts * tv);
  }

string Num(const double v) { return(DoubleToString(v, 6)); }

// Equity at the start of today (server time), kept across restarts.
double DayStartEquity()
  {
   string base = "Guardian_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN));
   double today = (double)((long)TimeCurrent() / 86400);
   double eq = AccountInfoDouble(ACCOUNT_EQUITY);
   if(!GlobalVariableCheck(base + "_day") || GlobalVariableGet(base + "_day") != today)
     {
      GlobalVariableSet(base + "_day", today);
      GlobalVariableSet(base + "_eq", eq);
     }
   return(GlobalVariableGet(base + "_eq"));
  }

//+------------------------------------------------------------------+
void OnTimer()
  {
   DayStartEquity();                      // record the day's start even when nothing trades
   ulong cur[];
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t > 0)
         Push(cur, t);
     }
   for(int i = OrdersTotal() - 1; i >= 0; i--)
     {
      ulong t = OrderGetTicket(i);
      if(t > 0)
         Push(cur, t);
     }
   if(!g_started)                         // trades open before Guardian started: no warning
     {
      ArrayResize(g_seen, 0);
      for(int i = 0; i < ArraySize(cur); i++)
         Push(g_seen, cur[i]);
      g_started = true;
      return;
     }
   for(int i = 0; i < ArraySize(cur); i++)
     {
      ulong t = cur[i];
      if(Find(g_seen, t) >= 0)
         continue;
      int w = Find(g_wait, t);
      if(w < 0)
        {
         Push(g_wait, t);
         int n = ArraySize(g_waitAt);
         ArrayResize(g_waitAt, n + 1);
         g_waitAt[n] = TimeLocal();
         continue;
        }
      if(TimeLocal() - g_waitAt[w] < GraceSeconds)
         continue;
      Push(g_seen, t);                    // a filled pending order keeps its ticket: one warning
      ArrayRemove(g_wait, w, 1);
      ArrayRemove(g_waitAt, w, 1);
      Judge(t);
     }
   // forget closed tickets so the lists stay small
   for(int i = ArraySize(g_seen) - 1; i >= 0; i--)
      if(Find(cur, g_seen[i]) < 0)
         ArrayRemove(g_seen, i, 1);
   for(int i = ArraySize(g_wait) - 1; i >= 0; i--)
      if(Find(cur, g_wait[i]) < 0)
        {
         ArrayRemove(g_wait, i, 1);
         ArrayRemove(g_waitAt, i, 1);
        }
  }

//+------------------------------------------------------------------+
void Judge(const ulong ticket)
  {
   string sym = "", side = "";
   double vol = 0, open = 0, sl = 0;
   if(PositionSelectByTicket(ticket))
     {
      sym  = PositionGetString(POSITION_SYMBOL);
      vol  = PositionGetDouble(POSITION_VOLUME);
      open = PositionGetDouble(POSITION_PRICE_OPEN);
      sl   = PositionGetDouble(POSITION_SL);
      side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY) ? "BUY" : "SELL";
     }
   else
      if(OrderSelect(ticket))
        {
         sym  = OrderGetString(ORDER_SYMBOL);
         vol  = OrderGetDouble(ORDER_VOLUME_CURRENT);
         open = OrderGetDouble(ORDER_PRICE_OPEN);
         sl   = OrderGetDouble(ORDER_SL);
         ENUM_ORDER_TYPE ot = (ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE);
         side = (ot == ORDER_TYPE_BUY_LIMIT || ot == ORDER_TYPE_BUY_STOP || ot == ORDER_TYPE_BUY_STOP_LIMIT)
                ? "BUY order" : "SELL order";
        }
      else
         return;

   double dist = (sl > 0) ? MathAbs(open - sl) : 0;
   double perLot = (dist > 0) ? PerLot(sym, dist) : -1;

   // the rest of the book
   int nOpen = 0, naked = 0;
   double openRisk = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
     {
      ulong t = PositionGetTicket(i);
      if(t == 0 || t == ticket)
         continue;
      nOpen++;
      double psl = PositionGetDouble(POSITION_SL);
      if(psl <= 0)
        {
         naked++;
         continue;
        }
      double pl = PerLot(PositionGetString(POSITION_SYMBOL), MathAbs(PositionGetDouble(POSITION_PRICE_OPEN) - psl));
      if(pl > 0)
         openRisk += pl * PositionGetDouble(POSITION_VOLUME);
     }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   string challenge = "{\"on\":false}";
   if(ChallengeStart > 0)
      challenge = "{\"on\":true,\"start\":" + Num(ChallengeStart) + ",\"daily_pct\":" + Num(DailyLossPct) +
                  ",\"max_pct\":" + Num(MaxLossPct) + ",\"today_pl\":" + Num(equity - DayStartEquity()) + "}";
   string body = "{\"key\":\"" + GuardianKey + "\",\"dev\":\"mt5-" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\"," +
                 "\"trade\":{\"sym\":\"" + sym + "\",\"side\":\"" + side + "\",\"lots\":" + Num(vol) +
                 ",\"stop\":" + Num(dist) + ",\"per_lot\":" + (perLot > 0 ? Num(perLot) : "null") + "}," +
                 "\"account\":{\"equity\":" + Num(equity) + ",\"risk_pct\":" + Num(RiskPercent) +
                 ",\"open_trades\":" + IntegerToString(nOpen) + ",\"open_risk\":" + Num(openRisk) +
                 ",\"open_no_stop\":" + IntegerToString(naked) + ",\"challenge\":" + challenge + "}}";

   string reply;
   if(!Ask(body, reply))
     {
      LocalCheck(sym, side, vol, dist, perLot, equity);
      return;
     }
   string lines[];
   int n = StringSplit(reply, '\n', lines);
   if(n < 2 || lines[0] == "OK")
     {
      Print("Guardian: ", sym, " ", side, " ", DoubleToString(vol, 2), " lots looks fine.");
      return;
     }
   if(lines[0] == "ERROR")
     {
      Print(lines[1]);
      return;
     }
   Warn(lines);
  }

// POST to staalwag.com. False when it can't be reached (the local check takes over).
bool Ask(const string body, string &reply)
  {
   char post[], res[];
   string headers;
   StringToCharArray(body, post, 0, WHOLE_ARRAY, CP_UTF8);
   ArrayResize(post, ArraySize(post) - 1);          // drop the trailing zero
   ResetLastError();
   int code = WebRequest("POST", ServerURL, "Content-Type: application/json\r\n", 8000, post, res, headers);
   if(code == -1)
     {
      if(GetLastError() == 4014 && !g_toldWeb)
        {
         g_toldWeb = true;
         Alert("Guardian: allow it online. Tools > Options > Expert Advisors > tick Allow WebRequest, add https://app.staalwag.com");
        }
      return(false);
     }
   if(code == 403)
     {
      if(!g_toldKey)
        {
         g_toldKey = true;
         Alert("Guardian: this key doesn't include Guardian. Only the basic size and stop checks will run.");
        }
      return(false);
     }
   if(code != 200)
      return(false);
   reply = CharArrayToString(res, 0, WHOLE_ARRAY, CP_UTF8);
   return(true);
  }

void Warn(string &lines[])
  {
   Print(lines[1]);
   if(PushToPhone && !SendNotification(lines[1]))
      TellPushOff();
   if(PopupOnPC)
     {
      Alert(lines[1]);
      for(int i = 2; i < ArraySize(lines); i++)
         if(StringLen(lines[i]) > 0)
            Alert("   ", lines[i]);
     }
  }

// Offline fallback: no stop, or more than the planned risk. Same words as the server.
void LocalCheck(const string sym, const string side, const double vol, const double dist,
                const double perLot, const double equity)
  {
   string what = sym + " " + side + " " + DoubleToString(vol, 2) + " lots";
   string reason = "";
   if(dist <= 0)
      reason = "No stop loss: without a stop the worst case is your whole account.";
   else
      if(perLot > 0 && equity > 0)
        {
         double pct = vol * perLot / equity * 100;
         if(pct > RiskPercent * 1.5)
            reason = StringFormat("Too big: the stop costs %.1f%% of your account. Safe size is %.2f lots.",
                                  pct, MathFloor(equity * RiskPercent / 100 / perLot * 100) / 100);
        }
   if(reason == "")
      return;
   string lines[3];
   lines[0] = "NO";
   lines[1] = "GUARDIAN NO. Sit this out. " + what + " " + reason;
   lines[2] = "(staalwag.com could not be reached, so news and time were not checked)";
   Warn(lines);
  }

void TellPushOff()
  {
   if(g_toldPush)
      return;
   g_toldPush = true;
   Alert("Guardian: phone pushes are off. Tools > Options > Notifications > Enable Push, paste your MetaQuotes ID.");
  }
//+------------------------------------------------------------------+
