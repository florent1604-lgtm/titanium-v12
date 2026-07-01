//+------------------------------------------------------------------+
//|                                     Level2_Binance_GUI_EA.mq5    |
//|                                              Antigravity Assistant|
//+------------------------------------------------------------------+
#property copyright "Antigravity Assistant"
#property link      ""
#property version   "2.00"

input string  BinanceSymbol = "BTCUSDT"; // Symbole sur Binance
input int     DepthLimit    = 15;        // Niveaux de profondeur (max 50)
input int     RefreshRate   = 500;       // Rafraîchissement (ms)
input int     PanelX        = 20;        // Position horizontale du panneau
input int     PanelY        = 30;        // Position verticale du panneau

struct DOMLevel {
   double price;
   double volume;
};

DOMLevel asks[];
DOMLevel bids[];

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
  {
   ArrayResize(asks, DepthLimit);
   ArrayResize(bids, DepthLimit);
   
   EventSetMillisecondTimer(RefreshRate);
   CreateGUI();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   EventKillTimer();
   DeleteGUI();
   ChartRedraw();
  }

void OnTimer()
  {
   string url = "https://api.binance.com/api/v3/depth?symbol=" + BinanceSymbol + "&limit=" + IntegerToString(DepthLimit);
   char post[], result[];
   string headers;
   
   int res = WebRequest("GET", url, "", 1000, post, result, headers);
   
   if(res == 200)
     {
      string json = CharArrayToString(result);
      if(ParseDOM(json))
        {
         UpdateGUI();
        }
     }
  }

//+------------------------------------------------------------------+
//| Parsing functions                                                |
//+------------------------------------------------------------------+
bool ParseDOM(string json)
  {
   int bids_pos = StringFind(json, "\"bids\":[");
   int asks_pos = StringFind(json, "\"asks\":[");
   
   if(asks_pos < 0 || bids_pos < 0) return false;
   
   string bids_str, asks_str;
   
   if(bids_pos < asks_pos)
     {
      bids_str = StringSubstr(json, bids_pos + 8, asks_pos - bids_pos - 10);
      asks_str = StringSubstr(json, asks_pos + 8);
     }
   else
     {
      asks_str = StringSubstr(json, asks_pos + 8, bids_pos - asks_pos - 10);
      bids_str = StringSubstr(json, bids_pos + 8);
     }
     
   ParseLevels(asks_str, asks);
   ParseLevels(bids_str, bids);
   return true;
  }

void ParseLevels(string array_str, DOMLevel &levels[])
  {
   string pairs[];
   int count = StringSplit(array_str, ']', pairs);
   int idx = 0;
   
   for(int i = 0; i < count && idx < DepthLimit; i++)
     {
      int start = StringFind(pairs[i], "[\"");
      if(start >= 0)
        {
         string data = StringSubstr(pairs[i], start + 2);
         StringReplace(data, "\"", "");
         string values[];
         if(StringSplit(data, ',', values) >= 2)
           {
            levels[idx].price = StringToDouble(values[0]);
            levels[idx].volume = StringToDouble(values[1]);
            idx++;
           }
        }
     }
  }

//+------------------------------------------------------------------+
//| GUI Dashboard Engine                                             |
//+------------------------------------------------------------------+
string prefix = "L2DOM_";
int bar_height = 18;
int panel_width = 300;

void CreateGUI()
  {
   int total_levels = DepthLimit * 2;
   int panel_height = 55 + (total_levels * bar_height) + 15;
   
   // Création du fond d'écran (Background Noir)
   CreateRect(prefix + "BG", PanelX, PanelY, panel_width, panel_height, clrBlack);
   CreateLabel(prefix + "TITLE", PanelX + 10, PanelY + 10, "Depth of Market (Niveau 2) - " + BinanceSymbol, clrWhite, 11, true);
   
   // Titres des colonnes
   CreateLabel(prefix + "HDR_PRICE", PanelX + 10, PanelY + 35, "PRIX", clrGray, 9);
   CreateLabel(prefix + "HDR_VOL", PanelX + 120, PanelY + 35, "VOLUME (BTC)", clrGray, 9);
   
   int start_y = PanelY + 55;
   
   // Création des barres pour les Vendeurs (Asks - Rouge)
   for(int i = 0; i < DepthLimit; i++)
     {
      int y = start_y + i * bar_height;
      CreateRect(prefix + "ASK_BAR_" + IntegerToString(i), PanelX + 5, y, 10, bar_height - 2, clrMaroon);
      CreateLabel(prefix + "ASK_PRICE_" + IntegerToString(i), PanelX + 10, y + 1, "-", clrLightPink, 10);
      CreateLabel(prefix + "ASK_VOL_" + IntegerToString(i), PanelX + 120, y + 1, "-", clrWhite, 10);
     }
     
   // Création des barres pour les Acheteurs (Bids - Vert)
   start_y = PanelY + 55 + (DepthLimit * bar_height) + 5;
   for(int i = 0; i < DepthLimit; i++)
     {
      int y = start_y + i * bar_height;
      CreateRect(prefix + "BID_BAR_" + IntegerToString(i), PanelX + 5, y, 10, bar_height - 2, clrDarkGreen);
      CreateLabel(prefix + "BID_PRICE_" + IntegerToString(i), PanelX + 10, y + 1, "-", clrLightGreen, 10);
      CreateLabel(prefix + "BID_VOL_" + IntegerToString(i), PanelX + 120, y + 1, "-", clrWhite, 10);
     }
  }

void UpdateGUI()
  {
   // Trouver le volume maximum pour adapter la taille des barres dynamiquement
   double max_vol = 0.0001;
   for(int i = 0; i < DepthLimit; i++)
     {
      if(asks[i].volume > max_vol) max_vol = asks[i].volume;
      if(bids[i].volume > max_vol) max_vol = bids[i].volume;
     }
     
   int max_bar_width = panel_width - 10;
   
   // Mise à jour des Vendeurs (Affichés du prix le plus haut vers le plus bas)
   for(int i = 0; i < DepthLimit; i++)
     {
      int src_idx = DepthLimit - 1 - i;
      string p = prefix + "ASK_";
      
      int width = (int)((asks[src_idx].volume / max_vol) * max_bar_width);
      if(width < 2) width = 2; // Largeur minimum
      
      ObjectSetInteger(0, p + "BAR_" + IntegerToString(i), OBJPROP_XSIZE, width);
      ObjectSetString(0, p + "PRICE_" + IntegerToString(i), OBJPROP_TEXT, DoubleToString(asks[src_idx].price, 2));
      ObjectSetString(0, p + "VOL_" + IntegerToString(i), OBJPROP_TEXT, DoubleToString(asks[src_idx].volume, 3));
     }
     
   // Mise à jour des Acheteurs (Affichés du prix le plus haut vers le plus bas)
   for(int i = 0; i < DepthLimit; i++)
     {
      string p = prefix + "BID_";
      
      int width = (int)((bids[i].volume / max_vol) * max_bar_width);
      if(width < 2) width = 2;
      
      ObjectSetInteger(0, p + "BAR_" + IntegerToString(i), OBJPROP_XSIZE, width);
      ObjectSetString(0, p + "PRICE_" + IntegerToString(i), OBJPROP_TEXT, DoubleToString(bids[i].price, 2));
      ObjectSetString(0, p + "VOL_" + IntegerToString(i), OBJPROP_TEXT, DoubleToString(bids[i].volume, 3));
     }
     
   ChartRedraw();
  }

void DeleteGUI()
  {
   ObjectsDeleteAll(0, prefix);
  }

//+------------------------------------------------------------------+
//| Fonctions utilitaires de dessin                                  |
//+------------------------------------------------------------------+
void CreateRect(string name, int x, int y, int w, int h, color clr)
  {
   ObjectCreate(0, name, OBJ_RECTANGLE_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetInteger(0, name, OBJPROP_XSIZE, w);
   ObjectSetInteger(0, name, OBJPROP_YSIZE, h);
   ObjectSetInteger(0, name, OBJPROP_BGCOLOR, clr);
   ObjectSetInteger(0, name, OBJPROP_BORDER_TYPE, BORDER_FLAT);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clrNONE);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
  }

void CreateLabel(string name, int x, int y, string text, color clr, int font_size, bool bold=false)
  {
   ObjectCreate(0, name, OBJ_LABEL, 0, 0, 0);
   ObjectSetInteger(0, name, OBJPROP_XDISTANCE, x);
   ObjectSetInteger(0, name, OBJPROP_YDISTANCE, y);
   ObjectSetString(0, name, OBJPROP_TEXT, text);
   ObjectSetInteger(0, name, OBJPROP_COLOR, clr);
   ObjectSetString(0, name, OBJPROP_FONT, bold ? "Segoe UI Bold" : "Segoe UI");
   ObjectSetInteger(0, name, OBJPROP_FONTSIZE, font_size);
   ObjectSetInteger(0, name, OBJPROP_CORNER, CORNER_LEFT_UPPER);
   ObjectSetInteger(0, name, OBJPROP_BACK, false);
   ObjectSetInteger(0, name, OBJPROP_SELECTABLE, false);
  }
//+------------------------------------------------------------------+
