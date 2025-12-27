"""
F1 Prediction Model: XGBoost-based race winner predictor.
Exposes tunable weighting to control grid influence vs recent form,
and allows circuit-specific overtaking adjustments.
Includes parameter calibration via historical race prediction errors.
"""
import pandas as pd
import numpy as np
from sklearn.preprocessing import RobustScaler
from typing import Optional, Dict, Tuple, cast, List
from dataclasses import dataclass, field
from sklearn.model_selection import train_test_split
from sklearn.calibration import CalibratedClassifierCV
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
from scipy.optimize import minimize, differential_evolution
from pathlib import Path
from datetime import datetime
import json

@dataclass
class PredictorConfig:
    grid_alpha: float = 0.147  
    temperature: float = 0.423 
    form_boost_weight: float = 0.170  
    circuit_overtaking_map: Dict[int, float] = field(default_factory=dict)


class F1Predictor:
    """XGBoost predictor for F1 race winners."""
    
    def __init__(self, results_df: pd.DataFrame, drivers_df: pd.DataFrame, constructors_df: pd.DataFrame,
                 config: Optional[PredictorConfig] = None):
        self.results = results_df.copy()
        self.drivers = drivers_df.copy()
        self.constructors = constructors_df.copy()
        self.config = config or PredictorConfig()
        
        self.feature_columns = [
            "QualifyingPosition", "GridPosition", "AvgQualifyingLast5",
            "AvgFinishLast5", "WinsLast5", "DriverPointsCum",
            "ConstructorPointsCum", "ConstructorWinsCum",
            "AvgFinishLast3", "WinsLast3", "ConstructorAvgFinishLast3",
            "CircuitWinRate", "CircuitAvgFinish",
            "CircuitPassRateLast5", "PaceGapToField",
            "TrackTempAvg", "WindSpeedAvg", "IsWet", "ConstructorRecentRank3"
        ]
        
        self.scaler: Optional[RobustScaler] = None
        self.model = None
        
        self._prepare_training_data()
        self._train_model()
    
    def _prepare_training_data(self):
        """Engineer features from historical data - optimized."""
        df = self.results.copy()
        
        # Target
        df["Win"] = (df["position"] == 1).astype(np.int8)
        
        # Basic positions
        df["GridPosition"] = df["grid"].fillna(20).replace(0, 20)
        df["QualifyingPosition"] = df["quali_position"].fillna(df["GridPosition"])
        
        # Sort once for rolling windows
        df = df.sort_values(["driverId", "date"])
        
        # Vectorized rolling statistics - 5 race average
        rolling_cols = {
            "QualifyingPosition": "AvgQualifyingLast5",
            "position": "AvgFinishLast5",
            "Win": "WinsLast5"
        }
        
        for col, new_col in rolling_cols.items():
            df[new_col] = (df.groupby("driverId")[col]
                          .transform(lambda x: x.rolling(5, min_periods=1).mean().shift(1))
                          .fillna(10 if col != "Win" else 0))
        
        # Recent 3-race form (higher weight on very recent performance)
        df["AvgFinishLast3"] = (df.groupby("driverId")["position"]
                                .transform(lambda x: x.rolling(3, min_periods=1).mean().shift(1))
                                .fillna(10))
        df["WinsLast3"] = (df.groupby("driverId")["Win"]
                           .transform(lambda x: x.rolling(3, min_periods=1).sum().shift(1))
                           .fillna(0))
        
        # Constructor recent form
        df["ConstructorAvgFinishLast3"] = (df.groupby("constructorId")["position"]
                                           .transform(lambda x: x.rolling(3, min_periods=1).mean().shift(1))
                                           .fillna(10))
        
        # Circuit-specific driver performance
        if "circuitId" in df.columns:
            circuit_stats = df.groupby(["driverId", "circuitId"]).agg({
                "Win": "sum",
                "position": "mean"
            }).reset_index()
            circuit_stats.columns = ["driverId", "circuitId", "CircuitWins", "CircuitAvgFinish"]
            circuit_stats["CircuitRaces"] = df.groupby(["driverId", "circuitId"]).size().values
            circuit_stats["CircuitWinRate"] = circuit_stats["CircuitWins"] / circuit_stats["CircuitRaces"]
            df = df.merge(circuit_stats[["driverId", "circuitId", "CircuitWinRate", "CircuitAvgFinish"]], 
                         on=["driverId", "circuitId"], how="left")
            df["CircuitWinRate"] = df["CircuitWinRate"].fillna(0)
            df["CircuitAvgFinish"] = df["CircuitAvgFinish"].fillna(10)
        else:
            df["CircuitWinRate"] = 0
            df["CircuitAvgFinish"] = 10
        
        # Cumulative stats
        df["DriverPointsCum"] = df.groupby("driverId")["points"].fillna(0).cumsum() - df["points"].fillna(0)
        df["ConstructorPointsCum"] = df.groupby("constructorId")["points"].fillna(0).cumsum() - df["points"].fillna(0)
        df["ConstructorWinsCum"] = df.groupby("constructorId")["Win"].cumsum() - df["Win"]
        
        # === NEW FEATURES ===
        # 1. Track Overtake Factor: Historic_Pass_Rate = Total Overtakes / Race Laps
        df["OvertakesCount"] = 0.0
        df["RaceLaps"] = 1.0
        for race_id in df["raceId"].unique():
            race_mask = df["raceId"] == race_id
            race_data = df.loc[race_mask, ["driverId", "grid", "position", "laps"]]
            if not race_data.empty:
                overtakes = (race_data["grid"] - race_data["position"]).clip(lower=0).sum()
                race_laps = race_data["laps"].max()
                df.loc[race_mask, "OvertakesCount"] = overtakes
                df.loc[race_mask, "RaceLaps"] = max(race_laps, 1)
        
        df["OvertakeRate"] = df["OvertakesCount"] / df["RaceLaps"]
        df["CircuitPassRateLast5"] = (
            df.groupby("circuitId")["OvertakeRate"]
            .transform(lambda x: x.rolling(5, min_periods=1).mean().shift(1))
            .fillna(0.1)
        )
        
        # 2. Performance Delta: Pace_Gap_To_Field = Car_Qualifying_Time - Median_Field_Qualifying_Time
        df["MedianQualTime"] = df.groupby("raceId")["qual_time_seconds"].transform("median")
        df["PaceGapToField"] = (df["qual_time_seconds"] - df["MedianQualTime"]).fillna(0.0)
        
        # 3. Weather conditions (already in DataFrame from data_loader)
        if "TrackTempAvg" not in df.columns:
            df["TrackTempAvg"] = 0.0
        if "WindSpeedAvg" not in df.columns:
            df["WindSpeedAvg"] = 0.0
        if "IsWet" not in df.columns:
            df["IsWet"] = 0
        
        # 4. Constructor Recent Rank (3-race average rank)
        df["ConstructorAvgFinishLast3_temp"] = (
            df.groupby("constructorId")["position"]
            .transform(lambda x: x.rolling(3, min_periods=1).mean().shift(1))
        )
        df["ConstructorRecentRank3"] = df.groupby("constructorId")["ConstructorAvgFinishLast3_temp"].rank()
        df["ConstructorRecentRank3"] = df.groupby("constructorId")["ConstructorRecentRank3"].transform(
            lambda x: x / x.max() if x.max() > 0 else 1.0
        )
        df = df.drop(columns=["ConstructorAvgFinishLast3_temp", "OvertakesCount", "RaceLaps", "MedianQualTime"])
        
        # Remove NaN rows
        df = df.dropna(subset=self.feature_columns + ["Win"])
        
        self.training_features = df[self.feature_columns]
        self.training_target = df["Win"]
        self.results = df
    
    def _train_model(self):
        """Train XGBoost with SMOTE and calibration."""
        X, y = self.training_features, self.training_target
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42, stratify=y)
        
        # Scale
        self.scaler = RobustScaler()
        X_train_scaled = self.scaler.fit_transform(X_train)
        X_test_scaled = self.scaler.transform(X_test)
        
        # Balance with SMOTE
        smote = SMOTE(random_state=42, k_neighbors=3)
        X_train_res, y_train_res = cast(Tuple[np.ndarray, pd.Series], smote.fit_resample(X_train_scaled, y_train))
        
        # Split for calibration
        X_train_core, X_calib, y_train_core, y_calib = train_test_split(
            X_train_res, y_train_res, test_size=0.15, random_state=42, stratify=y_train_res
        )
        
        # Train
        self.model = XGBClassifier(
            n_estimators=400, max_depth=4, learning_rate=0.05,
            subsample=0.85, colsample_bytree=0.85,
            min_child_weight=3, gamma=0.15,
            reg_lambda=2.5, reg_alpha=0.8,
            random_state=42, verbosity=0, use_label_encoder=False
        )
        self.model.fit(X_train_core, y_train_core, eval_set=[(X_test_scaled, y_test)], verbose=False)
        
        # Calibrate
        self.calibrator = CalibratedClassifierCV(self.model, method="sigmoid", cv="prefit")
        self.calibrator.fit(X_calib, y_calib)
        
        # Evaluate
        y_pred = (self.calibrator.predict_proba(X_test_scaled)[:, 1] >= 0.5).astype(int)
        print(f"Model Accuracy: {(y_pred == y_test).mean():.3f}")
    
    def predict_race(self, driver_codes: list, quali_positions: Dict[str, float],
                     circuit_id: int = 0, constructor_ids: Optional[Dict[str, str]] = None,
                     as_of_date: Optional[pd.Timestamp] = None,
                     as_of_year: Optional[int] = None, as_of_round: Optional[int] = None,
                     circuit_overtaking_score: Optional[float] = None) -> pd.DataFrame:
        """Predict race winner probabilities using data only up to the selected event.

        - If `as_of_date` is provided, uses rows with date strictly before it.
        - Else if `as_of_year` and `as_of_round` provided, uses rows prior to that round.
        - Otherwise, uses latest available history (no leakage protection possible).
        """
        prediction_data = []
        grid_for_weight = []
        
        for driver_code in driver_codes:
            driver = self.drivers[self.drivers["driver_code"] == driver_code]
            
            if driver.empty:
                # New driver defaults
                features = {col: 10.0 if "Position" in col or "Avg" in col else 0.0 
                           for col in self.feature_columns}
                features["QualifyingPosition"] = quali_positions.get(driver_code, 10)
                features["GridPosition"] = quali_positions.get(driver_code, 10)
                constructor_name = constructor_ids.get(driver_code, "Unknown") if constructor_ids else "Unknown"
            else:
                driver_id = driver.iloc[0]["driverId"]
                driver_history = self.results[self.results["driverId"] == driver_id]
                # Restrict history to before the selected event (avoid leakage)
                if as_of_date is not None:
                    driver_history = driver_history[driver_history["date"] < as_of_date]
                elif as_of_year is not None and as_of_round is not None:
                    driver_history = driver_history[
                        (driver_history["year"] < as_of_year) |
                        ((driver_history["year"] == as_of_year) & (driver_history["round"] < as_of_round))
                    ]
                
                # Get last known values or defaults
                features = {}
                for col in self.feature_columns:
                    if col == "QualifyingPosition" or col == "GridPosition":
                        features[col] = quali_positions.get(driver_code, 10)
                    elif col in ["CircuitWinRate", "CircuitAvgFinish", "CircuitPassRateLast5", "PaceGapToField", 
                                 "TrackTempAvg", "WindSpeedAvg", "IsWet", "ConstructorRecentRank3"]:
                        # Circuit-specific or weather stats: filter by circuitId
                        circuit_history = driver_history[driver_history["circuitId"] == circuit_id] if "circuitId" in driver_history.columns and circuit_id > 0 else pd.DataFrame()
                        if not circuit_history.empty and col in circuit_history.columns:
                            features[col] = circuit_history[col].iloc[-1]
                        else:
                            if col in ["CircuitWinRate", "ConstructorRecentRank3"]:
                                features[col] = 0.0
                            elif col == "CircuitAvgFinish":
                                features[col] = 10.0
                            elif col == "CircuitPassRateLast5":
                                features[col] = 0.1
                            elif col == "PaceGapToField":
                                features[col] = 0.0
                            else:
                                features[col] = 0.0
                    elif not driver_history.empty and col in driver_history.columns:
                        features[col] = driver_history[col].iloc[-1]
                    else:
                        features[col] = 10.0 if "Position" in col or "Avg" in col else 0.0
                
                # Constructor name
                constructor_name = constructor_ids.get(driver_code) if constructor_ids else None
                if constructor_name is None:
                    if not driver_history.empty:
                        constructor_name = driver_history["constructor_name"].iloc[-1]
                    else:
                        constructor_name = "Unknown"
            
            grid_for_weight.append(quali_positions.get(driver_code, 10))
            prediction_data.append({
                "driver_code": driver_code,
                "constructor_name": constructor_name,
                **features
            })
        
        if not prediction_data:
            return pd.DataFrame()
        
        # Predict
        X_pred = pd.DataFrame(prediction_data)[self.feature_columns]
        assert self.scaler is not None, "Scaler not initialized"
        X_pred_scaled = self.scaler.transform(X_pred)
        
        raw_probs = self.calibrator.predict_proba(X_pred_scaled)[:, 1]

        # Extract circuit overtaking (derived from CircuitPassRateLast5 or explicit parameter)
        circuit_pass_rates = np.array([d.get("CircuitPassRateLast5", 0.1) for d in prediction_data])
        circuit_pass_rates = np.clip(circuit_pass_rates, 0.0, 1.0)
        
        # Use circuit overtaking score or derive from pass rate
        if circuit_overtaking_score is None:
            ov = np.clip(circuit_pass_rates * 3.0, 0.0, 1.0)
        else:
            ov = np.full(len(prediction_data), float(circuit_overtaking_score))
            ov = np.clip(ov, 0.0, 1.0)

        # Grid weighting: reduce influence when overtaking is easier
        effective_alpha = np.maximum(0.0, self.config.grid_alpha * (1.0 - ov))
        grid_weights = np.exp(-effective_alpha * (np.array(grid_for_weight) - 1))
        probs = raw_probs * grid_weights
        if probs.sum() == 0:
            probs = raw_probs

        # Pace delta boost: fast cars get higher probabilities
        pace_gaps = np.array([d.get("PaceGapToField", 0.0) for d in prediction_data])
        pace_boost = np.exp(-0.1 * pace_gaps)  # Lower pace gap (faster) = higher boost
        probs = probs * pace_boost

        # Recent form boost (based on AvgFinishLast3 and weather/temp effects)
        recent = 1.0 / (np.array([d.get("AvgFinishLast3", 10.0) for d in prediction_data]) + 1e-6)
        recent = recent / (recent.mean() if recent.mean() != 0 else 1.0)
        
        # Weather effects: rain increases randomness (lower exponent = flatter probs), heat increases tire deg
        is_wet = np.array([d.get("IsWet", 0) for d in prediction_data])
        track_temp = np.array([d.get("TrackTempAvg", 0.0) for d in prediction_data])
        weather_factor = 1.0 + (0.3 * is_wet) + (0.05 * np.clip(track_temp / 30.0, 0.0, 1.0))
        
        form_w = np.maximum(0.0, self.config.form_boost_weight * (1.0 + ov))
        probs = probs * (1.0 + form_w * (recent - 1.0) * weather_factor)
        probs = np.clip(probs, 1e-12, None)

        # Temperature scaling and normalization
        temperature = np.maximum(1e-3, float(self.config.temperature))
        # Rain flattens (increases temperature), dry sharpens
        adjusted_temp = temperature * (1.5 if np.any(is_wet > 0) else 1.0)
        probs = np.exp(np.log(probs) / adjusted_temp)
        probs = probs / probs.sum()
        
        results = pd.DataFrame(prediction_data)[["driver_code", "constructor_name"]].copy()
        results["win_probability"] = probs * 100
        
        return pd.DataFrame(results).sort_values(by="win_probability", ascending=False)
    
    def get_driver_standings(self, year: int = 2024) -> pd.DataFrame:
        """Get driver standings for a specific year."""
        grouped = (self.results[self.results["year"] == year]
                .groupby("driverId", as_index=False)
                .agg({"points": "sum", "Win": "sum", "driver_code": "first", "surname": "first"}))
        grouped_df = pd.DataFrame(grouped)
        standings = grouped_df.sort_values(by="points", ascending=False).loc[:, ["driver_code", "surname", "points", "Win"]].copy()
        
        standings.columns = ["Driver", "Surname", "Points", "Wins"]
        return cast(pd.DataFrame, standings)
    
    def get_constructor_standings(self, year: int = 2024) -> pd.DataFrame:
        """Get constructor standings for a specific year."""
        grouped = (self.results[self.results["year"] == year]
                .groupby("constructorId", as_index=False)
                .agg({"points": "sum", "Win": "sum", "constructor_name": "first"}))
        grouped_df = pd.DataFrame(grouped)
        standings = grouped_df.sort_values(by="points", ascending=False).loc[:, ["constructor_name", "points", "Win"]].copy()
        
        standings.columns = ["Constructor", "Points", "Wins"]
        return cast(pd.DataFrame, standings)
    
    def get_active_drivers(self) -> pd.DataFrame:
        """Get active drivers from most recent season."""
        latest_year = self.results["year"].max()
        return (self.results[self.results["year"] == latest_year]
               [["driver_code", "surname", "constructor_name"]]
               .drop_duplicates()
               .sort_values("surname"))


class PredictorCalibrator:
    """Learn optimal PredictorConfig parameters from historical race predictions."""
    
    def __init__(self, predictor: F1Predictor):
        self.predictor = predictor
        self.calibration_history = []
    
    def _evaluate_config(self, param_array: np.ndarray, races_data: List[Dict]) -> float:
        """
        Evaluate a parameter configuration on historical races.
        Returns loss (lower is better).
        
        param_array: [grid_alpha, form_boost_weight, temperature]
        races_data: list of dicts with 'year', 'round', 'driver_codes', 'quali_positions', 'constructor_mapping', 'actual_winner'
        """
        config = PredictorConfig(
            grid_alpha=float(param_array[0]),
            form_boost_weight=float(param_array[1]),
            temperature=float(param_array[2])
        )
        
        # Temporarily set config
        old_config = self.predictor.config
        self.predictor.config = config
        
        correct = 0
        total = len(races_data)
        
        try:
            for race in races_data:
                predictions = self.predictor.predict_race(
                    driver_codes=race['driver_codes'],
                    quali_positions=race['quali_positions'],
                    constructor_ids=race['constructor_mapping'],
                    as_of_year=race['year'],
                    as_of_round=race['round']
                )
                
                if not predictions.empty:
                    # Winner-focused metric: Hit@1 (top-1 correctness)
                    top_1 = predictions.iloc[0]['driver_code']
                    if race['actual_winner'] == top_1:
                        correct += 1
        finally:
            # Restore old config
            self.predictor.config = old_config
        
        # Loss: minimize misses (higher accuracy = lower loss)
        loss = 1.0 - (correct / total if total > 0 else 0.0)
        return loss
    
    def _prepare_calibration_races(self, min_year: int = 2020, max_races: int = 50) -> List[Dict]:
        """Prepare past races for calibration."""
        races_data = []
        
        # Get races from specified year onwards
        df = self.predictor.results[self.predictor.results['year'] >= min_year].copy()
        df = pd.DataFrame(df).sort_values(by='date')
        
        race_groups = df.groupby(['year', 'round']).first().reset_index()
        
        for idx, (_, race_row) in enumerate(race_groups.iterrows()):
            if len(races_data) >= max_races:
                break
            
            year = int(race_row['year'])
            round_num = int(race_row['round'])
            
            # Get results for this race
            race_results = df[(df['year'] == year) & (df['round'] == round_num)]
            
            if race_results.empty:
                continue
            
            # Find actual winner
            winner = race_results[race_results['position'] == 1.0]
            if winner.empty:
                continue
            
            actual_winner = winner.iloc[0]['driver_code']
            
            # Get driver codes and quali positions
            driver_codes = race_results['driver_code'].unique().tolist()
            quali_positions = {}
            constructor_mapping = {}
            
            for code in driver_codes:
                driver_data = race_results[race_results['driver_code'] == code]
                if not driver_data.empty:
                    quali_pos = driver_data['quali_position'].dropna().iloc[0] if not driver_data['quali_position'].dropna().empty else 10.0
                    constructor = driver_data['constructor_name'].iloc[0]
                    quali_positions[code] = float(quali_pos)
                    constructor_mapping[code] = constructor
            
            races_data.append({
                'year': year,
                'round': round_num,
                'driver_codes': driver_codes,
                'quali_positions': quali_positions,
                'constructor_mapping': constructor_mapping,
                'actual_winner': actual_winner
            })
        
        return races_data
    
    def calibrate(self, min_year: int = 2022, max_races: int = 50, method: str = 'differential_evolution') -> PredictorConfig:
        """
        Optimize prediction parameters using historical race data.
        
        Args:
            min_year: Start calibration from this year onwards
            max_races: Max number of races to use for calibration
            method: 'differential_evolution' (global) or 'powell' (local)
        
        Returns:
            Optimized PredictorConfig
        """
        print(f"\n[Calibration] Preparing {max_races} races for parameter optimization (from {min_year}+)...")
        races_data = self._prepare_calibration_races(min_year=min_year, max_races=max_races)
        
        if len(races_data) < 5:
            print(f"[Calibration] Warning: Only {len(races_data)} races available for calibration")
            return self.predictor.config
        
        print(f"[Calibration] Using {len(races_data)} races to calibrate parameters...")
        
        # Define bounds for parameters
        # grid_alpha: [0.05, 0.25]
        # form_boost_weight: [0.15, 0.50]
        # temperature: [0.3, 1.0]
        bounds = [
            (0.05, 0.25),
            (0.15, 0.50),
            (0.30, 1.00)
        ]
        
        if method == 'differential_evolution':
            print("[Calibration] Using differential evolution (global optimization)...")
            result = differential_evolution(
                lambda p: self._evaluate_config(p, races_data),
                bounds,
                seed=42,
                maxiter=30,
                popsize=15,
                workers=1,
                updating='deferred'
            )
        else:
            print("[Calibration] Using Powell (local optimization)...")
            x0 = [0.14, 0.30, 0.5]
            result = minimize(
                lambda p: self._evaluate_config(p, races_data),
                x0,
                method='Powell',
                options={'maxiter': 50}
            )
        
        optimal_config = PredictorConfig(
            grid_alpha=float(result.x[0]),
            form_boost_weight=float(result.x[1]),
            temperature=float(result.x[2])
        )
        
        # Evaluate improvement
        old_loss = self._evaluate_config(
            np.array([self.predictor.config.grid_alpha, self.predictor.config.form_boost_weight, self.predictor.config.temperature]),
            races_data
        )
        new_loss = result.fun
        old_acc = 1 - old_loss
        new_acc = 1 - new_loss
        
        print(f"[Calibration] Optimization complete!")
        print(f"  Old Hit@1: {old_acc * 100:.1f}%")
        print(f"  New Hit@1: {new_acc * 100:.1f}%")
        print(f"  Improvement: +{(new_acc - old_acc) * 100:.1f}%")
        print(f"  Parameters: grid_alpha={result.x[0]:.3f}, form_boost_weight={result.x[1]:.3f}, temperature={result.x[2]:.3f}")
        
        optimal_config = PredictorConfig(
            grid_alpha=float(result.x[0]),
            form_boost_weight=float(result.x[1]),
            temperature=float(result.x[2])
        )
        
        # Save calibration results to JSON
        results_json = {
            "timestamp": datetime.now().isoformat(),
            "min_year": min_year,
            "max_races": max_races,
            "num_races_used": len(races_data),
            "old_accuracy": float(old_acc),
            "new_accuracy": float(new_acc),
            "improvement": float(new_acc - old_acc),
            "old_config": {
                "grid_alpha": float(self.predictor.config.grid_alpha),
                "form_boost_weight": float(self.predictor.config.form_boost_weight),
                "temperature": float(self.predictor.config.temperature)
            },
            "optimized_config": {
                "grid_alpha": float(result.x[0]),
                "form_boost_weight": float(result.x[1]),
                "temperature": float(result.x[2])
            }
        }
        
        # Save to file
        results_file = Path("calibration_results.json")
        with open(results_file, 'w') as f:
            json.dump(results_json, f, indent=2)
        print(f"\n[SAVED] Results to {results_file}")
        
        self.calibration_history.append({
            'old_accuracy': old_acc,
            'new_accuracy': new_acc,
            'config': optimal_config
        })
        
        return optimal_config


def generate_calibration_report(results_file: str = "calibration_results.json") -> str:
    """
    Generate a markdown report from calibration results.
    
    Args:
        results_file: Path to calibration_results.json
    
    Returns:
        Markdown report as string
    """
    results_path = Path(results_file)
    if not results_path.exists():
        return "No calibration results found. Run calibration first (option 4 in CLI)."
    
    with open(results_path) as f:
        data = json.load(f)
    
    report = f"""# F1 Model Calibration Report

**Generated:** {data['timestamp']}

## Summary
- **Races Used:** {data['num_races_used']} races (from {data['min_year']} onwards)
- **Old Hit@1:** {data['old_accuracy']*100:.1f}%
- **New Hit@1:** {data['new_accuracy']*100:.1f}%
- **Improvement:** +{data['improvement']*100:.1f}%

## Optimized Parameters

### Before Calibration
- grid_alpha: {data['old_config']['grid_alpha']:.4f}
- form_boost_weight: {data['old_config']['form_boost_weight']:.4f}
- temperature: {data['old_config']['temperature']:.4f}

### After Calibration (OPTIMIZED)
- grid_alpha: {data['optimized_config']['grid_alpha']:.4f}
- form_boost_weight: {data['optimized_config']['form_boost_weight']:.4f}
- temperature: {data['optimized_config']['temperature']:.4f}

## To Hardcode These Parameters

Copy this into `f1_model.py` line 20 (PredictorConfig defaults):

```python
@dataclass
class PredictorConfig:
    grid_alpha: float = {data['optimized_config']['grid_alpha']:.4f}  # Was {data['old_config']['grid_alpha']:.4f}
    temperature: float = {data['optimized_config']['temperature']:.4f}  # Was {data['old_config']['temperature']:.4f}
    form_boost_weight: float = {data['optimized_config']['form_boost_weight']:.4f}  # Was {data['old_config']['form_boost_weight']:.4f}
    circuit_overtaking_map: Dict[int, float] = field(default_factory=dict)
```

Then all future runs will use these optimized parameters by default.
"""
    return report


def print_calibration_report(results_file: str = "calibration_results.json"):
    """Print the calibration report to console."""
    report = generate_calibration_report(results_file)
    print(report)


def save_calibration_report(results_file: str = "calibration_results.json", output_file: str = "CALIBRATION_REPORT.md"):
    """Save the calibration report to a markdown file."""
    report = generate_calibration_report(results_file)
    with open(output_file, 'w') as f:
        f.write(report)
    print(f"Report saved to {output_file}")

