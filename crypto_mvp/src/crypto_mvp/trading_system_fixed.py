    def _load_or_initialize_portfolio(self) -> None:
        """Load existing portfolio state or initialize with default values."""
        try:
            # Get target initial capital from config
            target_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            
            # Try to load existing state from persistent store
            latest_cash_equity = self.state_store.get_latest_cash_equity()
            existing_positions = self.state_store.get_positions()
            
            if latest_cash_equity is not None:
                stored_cash = latest_cash_equity["cash_balance"]
                stored_equity = latest_cash_equity["total_equity"]
                
                # Check if there's a significant capital change (more than 20% difference)
                # Use the larger of cash or equity for comparison to catch both scenarios
                stored_value = max(stored_cash, stored_equity)
                capital_change_ratio = abs(target_capital - stored_value) / stored_value
                significant_change = capital_change_ratio > 0.2
                
                self.logger.debug(f"Capital change detection: stored_cash=${stored_cash:,.2f}, stored_equity=${stored_equity:,.2f}, target=${target_capital:,.2f}, ratio={capital_change_ratio:.1%}, significant={significant_change}")
                
                if significant_change:
                    self.logger.warning(f"Significant capital change detected: stored=${stored_cash:,.2f} -> target=${target_capital:,.2f} ({capital_change_ratio:.1%} change)")
                    self.logger.info("Clearing existing positions and starting fresh with new capital")
                    
                    # Clear existing positions and reset to target capital
                    self.state_store.clear_all_positions()
                    self.portfolio["cash_balance"] = target_capital
                    self.portfolio["equity"] = target_capital
                    self.portfolio["positions"] = {}
                    
                    # Save the fresh state
                    self._save_initial_portfolio_state(target_capital)
                    
                    self.logger.info(f"Initialized fresh portfolio with capital=${target_capital:,.2f}")
                else:
                    # Load existing state from store (no significant capital change)
                    self.portfolio["cash_balance"] = latest_cash_equity["cash_balance"]
                    self.portfolio["total_fees"] = latest_cash_equity["total_fees"]
                    
                    # Load positions into memory cache (positions are already in store)
                    self.portfolio["positions"] = {}
                    for pos in existing_positions:
                        symbol = pos["symbol"]
                        self.portfolio["positions"][symbol] = {
                            "quantity": pos["quantity"],
                            "entry_price": pos["entry_price"],
                            "current_price": pos["current_price"],
                            "unrealized_pnl": pos["unrealized_pnl"],
                            "strategy": pos["strategy"]
                        }
                    
                    # Calculate equity using current mark prices (not stored outdated value)
                    stored_equity = latest_cash_equity["total_equity"]
                    current_equity = self._get_total_equity()
                    self.portfolio["equity"] = current_equity
                    
                    # Log the difference between stored and calculated equity
                    equity_change = current_equity - stored_equity
                    equity_change_pct = (equity_change / stored_equity * 100) if stored_equity > 0 else 0
                    
                    self.logger.info(f"Loaded existing portfolio from store: cash=${self.portfolio['cash_balance']:,.2f}, equity=${current_equity:,.2f} (was ${stored_equity:,.2f} stored, {equity_change:+.2f} {equity_change_pct:+.1f}%), positions={len(existing_positions)}")
            else:
                # Initialize with config values and save to store
                self.portfolio["equity"] = target_capital
                self.portfolio["cash_balance"] = target_capital
                self.portfolio["total_fees"] = 0.0
                self.portfolio["positions"] = {}
                
                # Save initial state to persistent store
                self._save_initial_portfolio_state(target_capital)
                self.logger.info(f"Initialized new portfolio in store: equity=${target_capital:,.2f}")
                
        except Exception as e:
            self.logger.error(f"Failed to load/initialize portfolio: {e}")
            # Fallback to default initialization
            initial_capital = self.config.get("trading", {}).get("initial_capital", 100000.0)
            self.portfolio["equity"] = initial_capital
            self.portfolio["cash_balance"] = initial_capital
            self.portfolio["total_fees"] = 0.0
            self.portfolio["positions"] = {}
            self.logger.warning(f"Using fallback initialization with capital=${initial_capital:,.2f}")
