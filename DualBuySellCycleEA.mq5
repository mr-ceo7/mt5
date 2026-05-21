//+------------------------------------------------------------------+
//|                                         DualBuySellCycleEA.mq5   |
//|                                                      mr-ceo7     |
//|                                                                  |
//+------------------------------------------------------------------+
#property copyright "mr-ceo7"
#property link      ""
#property version   "1.00"

// Standard library for trade operations
#include <Trade\Trade.mqh>

// Input parameters
input double InpLotSize             = 0.01;      // Lot Size
input double InpRiskUSD            = 1.0;       // Risk Amount (USD)
input double InpTargetUSD          = 2.5;       // Target Profit (USD)
input double InpStabilizeOffsetUSD = 0.5;       // Stabilize Offset (USD)
input ulong  InpMagicNumber        = 888888;    // Magic Number

// Global trade object
CTrade trade;

// State variable keys for Global Variables
string stage_var_name;
string max_profit_var_name;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   // Set magic number for trade operations
   trade.SetExpertMagicNumber(InpMagicNumber);
   
   // Build global variable names for state persistence
   string prefix = _Symbol + "_" + IntegerToString(InpMagicNumber) + "_";
   stage_var_name = prefix + "stage";
   max_profit_var_name = prefix + "max_profit";
   
   // Initialize state variables if they do not exist
   if(!GlobalVariableCheck(stage_var_name))
   {
      GlobalVariableSet(stage_var_name, 1.0);
   }
   if(!GlobalVariableCheck(max_profit_var_name))
   {
      GlobalVariableSet(max_profit_var_name, -99999.0);
   }
   
   return(INIT_SUCCEEDED);
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   // Keep global variables persisted
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // 1. Scan current active positions for this symbol and magic number
   int buy_count = 0;
   int sell_count = 0;
   ulong buy_ticket = 0;
   ulong sell_ticket = 0;
   double buy_profit = 0;
   double sell_profit = 0;
   
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(PositionGetSymbol(i) == _Symbol && PositionGetInteger(POSITION_MAGIC) == InpMagicNumber)
      {
         ulong ticket = PositionGetInteger(POSITION_TICKET);
         long type = PositionGetInteger(POSITION_TYPE);
         double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
         
         if(type == POSITION_TYPE_BUY)
         {
            buy_count++;
            buy_ticket = ticket;
            buy_profit = profit;
         }
         else if(type == POSITION_TYPE_SELL)
         {
            sell_count++;
            sell_ticket = ticket;
            sell_profit = profit;
         }
      }
   }
   
   // Get current state
   int current_stage = (int)GlobalVariableGet(stage_var_name);
   double max_stage2_profit = GlobalVariableGet(max_profit_var_name);
   
   // --- Stage 1: Both legs active (or waiting to be opened) ---
   if(current_stage == 1)
   {
      // If no positions are active, start a new cycle by opening buy and sell
      if(buy_count == 0 && sell_count == 0)
      {
         PrintFormat("[%s] Starting new Dual Buy-Sell cycle. Placing BUY and SELL orders.", _Symbol);
         
         // Clear any stored peak profit
         max_stage2_profit = -99999.0;
         GlobalVariableSet(max_profit_var_name, max_stage2_profit);
         
         // Open BUY order
         if(!trade.Buy(InpLotSize, _Symbol))
         {
            PrintFormat("[%s] Failed to open BUY order: %s", _Symbol, trade.ResultRetcodeDescription());
         }
         
         // Open SELL order
         if(!trade.Sell(InpLotSize, _Symbol))
         {
            PrintFormat("[%s] Failed to open SELL order: %s", _Symbol, trade.ResultRetcodeDescription());
         }
         return;
      }
      
      // If we only have 1 position active in Stage 1, it's an incomplete setup
      if((buy_count == 1 && sell_count == 0) || (buy_count == 0 && sell_count == 1))
      {
         ulong single_ticket = (buy_count == 1) ? buy_ticket : sell_ticket;
         PrintFormat("[%s] Incomplete Stage 1 setup detected. Closing position %d and resetting cycle.", _Symbol, single_ticket);
         trade.PositionClose(single_ticket);
         
         // Reset state
         GlobalVariableSet(stage_var_name, 1.0);
         GlobalVariableSet(max_profit_var_name, -99999.0);
         return;
      }
      
      // If both positions are active, check if either has hit the risk limit (InpRiskUSD)
      if(buy_count == 1 && sell_count == 1)
      {
         // Check BUY leg risk limit
         if(buy_profit <= -InpRiskUSD)
         {
            PrintFormat("[%s] BUY position %d hit risk limit of -$%.2f (Profit: $%.2f). Closing and transitioning to Stage 2.", _Symbol, buy_ticket, InpRiskUSD, buy_profit);
            if(trade.PositionClose(buy_ticket))
            {
               GlobalVariableSet(stage_var_name, 2.0);
               GlobalVariableSet(max_profit_var_name, sell_profit);
            }
            return;
         }
         
         // Check SELL leg risk limit
         if(sell_profit <= -InpRiskUSD)
         {
            PrintFormat("[%s] SELL position %d hit risk limit of -$%.2f (Profit: $%.2f). Closing and transitioning to Stage 2.", _Symbol, sell_ticket, InpRiskUSD, sell_profit);
            if(trade.PositionClose(sell_ticket))
            {
               GlobalVariableSet(stage_var_name, 2.0);
               GlobalVariableSet(max_profit_var_name, buy_profit);
            }
            return;
         }
      }
   }
   
   // --- Stage 2: Trailing the remaining winning leg ---
   else if(current_stage == 2)
   {
      // If no positions are active, reset to Stage 1
      if(buy_count == 0 && sell_count == 0)
      {
         PrintFormat("[%s] Remaining leg no longer active. Resetting cycle to Stage 1.", _Symbol);
         GlobalVariableSet(stage_var_name, 1.0);
         GlobalVariableSet(max_profit_var_name, -99999.0);
         return;
      }
      
      // If both positions are active in Stage 2 (unexpected state), reset to Stage 1 and close all
      if(buy_count == 1 && sell_count == 1)
      {
         PrintFormat("[%s] Unexpected state: both legs active in Stage 2. Closing all and resetting.", _Symbol);
         trade.PositionClose(buy_ticket);
         trade.PositionClose(sell_ticket);
         GlobalVariableSet(stage_var_name, 1.0);
         GlobalVariableSet(max_profit_var_name, -99999.0);
         return;
      }
      
      // We have exactly one position active in Stage 2
      ulong active_ticket = (buy_count == 1) ? buy_ticket : sell_ticket;
      double active_profit = (buy_count == 1) ? buy_profit : sell_profit;
      string pos_type_str = (buy_count == 1) ? "BUY" : "SELL";
      
      // Update peak profit
      if(max_stage2_profit == -99999.0 || active_profit > max_stage2_profit)
      {
         max_stage2_profit = active_profit;
         GlobalVariableSet(max_profit_var_name, max_stage2_profit);
      }
      
      // Calculate dynamic trailing stop loss level (if active)
      // S = target_usd + stabilize_offset_usd
      // V = target_usd + stabilize_offset_usd + risk_usd
      double R = InpRiskUSD;
      double T = InpTargetUSD;
      double O = InpStabilizeOffsetUSD;
      double stabilize_limit = T + O;
      double trailing_sl_pnl = -99999.0;
      
      if(max_stage2_profit >= stabilize_limit)
      {
         double transition_limit = stabilize_limit + R;
         if(max_stage2_profit < transition_limit)
         {
            // Interpolate from T (at max_profit = stabilize_limit) to T + O (at max_profit = transition_limit)
            double fraction = (max_stage2_profit - stabilize_limit) / R;
            trailing_sl_pnl = T + O * fraction;
         }
         else
         {
            // Maintain constant distance of risk_usd below max_profit
            trailing_sl_pnl = max_stage2_profit - R;
         }
      }
      
      // Check exits
      if(trailing_sl_pnl != -99999.0 && active_profit <= trailing_sl_pnl)
      {
         PrintFormat("[%s] Active %s position %d hit trailing stop loss at $%.2f (Profit: $%.2f, Peak: $%.2f). Closing.", 
                     _Symbol, pos_type_str, active_ticket, trailing_sl_pnl, active_profit, max_stage2_profit);
         trade.PositionClose(active_ticket);
         
         // Reset state
         GlobalVariableSet(stage_var_name, 1.0);
         GlobalVariableSet(max_profit_var_name, -99999.0);
      }
      else if(active_profit <= -R)
      {
         PrintFormat("[%s] Active %s position %d hit stop loss/risk limit of -$%.2f (Profit: $%.2f). Closing.", 
                     _Symbol, pos_type_str, active_ticket, R, active_profit);
         trade.PositionClose(active_ticket);
         
         // Reset state
         GlobalVariableSet(stage_var_name, 1.0);
         GlobalVariableSet(max_profit_var_name, -99999.0);
      }
   }
}
