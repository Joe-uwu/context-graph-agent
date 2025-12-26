"""
Data loader: Downloads, cleans, and manages F1 historical and live data.
Uses Kaggle dataset (1950-2024) + FastF1 for current session data.
"""
import os
import warnings
from typing import Tuple, Optional, cast
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

try:
    import kagglehub
except ImportError:
    raise ImportError("kagglehub required: pip install kagglehub")

try:
    import fastf1
    cache_dir = os.path.join(os.path.dirname(__file__), ".fastf1_cache")
    os.makedirs(cache_dir, exist_ok=True)
    fastf1.Cache.enable_cache(cache_dir)
except ImportError:
    fastf1 = None


class F1DataLoader:
    """Load and clean F1 historical and live data with caching."""
    
    _instance = None
    _data_cache = None
    
    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, min_year: int = 2010, max_year: int = 2025):
        if F1DataLoader._data_cache is not None:
            self.__dict__.update(F1DataLoader._data_cache)
            return
            
        self.min_year = min_year
        self.max_year = max_year
        self._load_data()
    
    def _load_data(self):
        """Load historical data from Kaggle with optimized processing."""
        print("Loading F1 historical data from Kaggle...")
        dataset_path = self._download_dataset()
        
        # Read all CSVs in parallel
        base = dataset_path
        results = pd.read_csv(
            os.path.join(base, "results.csv"),
            na_values=['\\N']
        )
        races = pd.read_csv(os.path.join(base, "races.csv"), parse_dates=['date'])
        qualifying = pd.read_csv(os.path.join(base, "qualifying.csv"), na_values=['\\N'])
        drivers = pd.read_csv(os.path.join(base, "drivers.csv"))
        constructors = pd.read_csv(os.path.join(base, "constructors.csv"))
        
        # Filter by year first (reduces merge size)
        races = races[(races["year"] >= self.min_year) & (races["year"] <= self.max_year)]
        race_ids = races["raceId"].values
        results = results[results["raceId"].isin(race_ids)]
        qualifying = qualifying[qualifying["raceId"].isin(race_ids)]
        
        # Vectorized cleaning
        for col in ["position", "grid", "points", "laps"]:
            if col in results.columns:
                results[col] = pd.to_numeric(results[col], errors="coerce")
        
        qualifying["position"] = pd.to_numeric(qualifying["position"], errors="coerce")

        # Parse qualifying times to seconds (best of Q1/Q2/Q3)
        def _parse_time_to_seconds(val):
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            s = str(val).strip()
            if not s:
                return None
            try:
                parts = s.split(":")
                if len(parts) == 2:
                    minutes = float(parts[0])
                    seconds = float(parts[1])
                    return minutes * 60.0 + seconds
                return float(s)
            except Exception:
                return None

        for col in ["q1", "q2", "q3"]:
            if col in qualifying.columns:
                qualifying[col + "_sec"] = qualifying[col].apply(_parse_time_to_seconds)
        qualifying["qual_time_seconds"] = qualifying[["q1_sec", "q2_sec", "q3_sec"]].min(axis=1)
        
        # Single merge operation with all metadata
        drivers["driver_code"] = drivers["code"]
        constructors["constructor_name"] = constructors["name"]
        
        results = (results
                   .merge(races[["raceId", "year", "round", "circuitId", "date", "name"]], on="raceId", how="left")
                   .merge(drivers[["driverId", "driver_code", "surname"]], on="driverId", how="left")
                   .merge(constructors[["constructorId", "constructor_name"]], on="constructorId", how="left")
                   .merge(qualifying[["raceId", "driverId", "position", "qual_time_seconds"]].rename(columns={"position": "quali_position"}),
                          on=["raceId", "driverId"], how="left"))
        
        # Add weather defaults for Kaggle data (all 0)
        results["TrackTempAvg"] = 0.0
        results["WindSpeedAvg"] = 0.0
        results["IsWet"] = 0
        
        self.results = results
        self.races = races
        self.qualifying = qualifying
        self.drivers = drivers
        self.constructors = constructors
        
        # Cache for singleton
        F1DataLoader._data_cache = self.__dict__.copy()
        
        print(f"[OK] Loaded {len(results)} results, {len(races)} races")
    
    def _download_dataset(self) -> str:
        """Download Kaggle F1 dataset."""
        try:
            return kagglehub.dataset_download("rohanrao/formula-1-world-championship-1950-2024")
        except:
            return kagglehub.dataset_download("rohanrao/formula-1-world-championship-1950-2020")
    
    def get_current_grid(self) -> pd.DataFrame:
        """Get 2025 F1 grid."""
        grid = {
            "VER": ("Verstappen", "Red Bull Racing"), "NOR": ("Norris", "McLaren"),
            "PIA": ("Piastri", "McLaren"), "LEC": ("Leclerc", "Ferrari"),
            "SAI": ("Sainz", "Ferrari"), "HAM": ("Hamilton", "Mercedes"),
            "RUS": ("Russell", "Mercedes"), "ALO": ("Alonso", "Aston Martin"),
            "STR": ("Stroll", "Aston Martin"), "ALB": ("Albon", "Williams"),
            "COL": ("Colton", "Williams"), "HUL": ("Hulkenberg", "Haas"),
            "MAG": ("Magnussen", "Haas"), "RIC": ("Ricciardo", "RB"),
            "TSU": ("Tsunoda", "RB"), "GAS": ("Gasly", "Alpine"),
            "RHC": ("Doohan", "Alpine"), "BOT": ("Bottas", "Alfa Romeo"),
            "ZHO": ("Zhou", "Alfa Romeo"), "LAW": ("Bearman", "Haas"),
        }
        
        return pd.DataFrame([
            {"driver_code": code, "surname": name, "team_name": team}
            for code, (name, team) in grid.items()
        ])
    
    def get_live_qualifying(self, year: int = 2025, round_num: int = 1) -> Optional[pd.DataFrame]:
        """Fetch live qualifying data from FastF1."""
        if fastf1 is None:
            return None
        
        try:
            session = fastf1.get_session(year, round_num, "Q")
            session.load()
            
            qual_data = []
            for pos, driver_code in enumerate(session.drivers, 1):
                qual_data.append({"driver_code": driver_code, "quali_position": pos})
            
            return pd.DataFrame(qual_data) if qual_data else None
        except:
            return None
    
    def get_current_session_info(self, year: int = 2025, round_num: int = 1) -> Optional[dict]:
        """Get current session info from FastF1, including event date."""
        if fastf1 is None:
            return None
        
        try:
            # Get event date via schedule
            try:
                sched = fastf1.get_event_schedule(year)
                event_row = sched[sched["RoundNumber"] == round_num]
                event_date = pd.to_datetime(event_row.iloc[0]["EventDate"]) if not event_row.empty else None
            except Exception:
                event_date = None

            session = fastf1.get_session(year, round_num, "Q")
            session.load()
            
            drivers_info = [
                {
                    "driver_code": code,
                    "team_name": session.get_driver(code).get("TeamName", "Unknown"),
                }
                for code in session.drivers
            ]
            
            return {"drivers": drivers_info, "year": year, "round": round_num, "event_date": event_date}
        except:
            return None
    
    def get_fastf1_race_results(self, year: int, round_num: int) -> Optional[pd.DataFrame]:
        """Fetch completed race results from FastF1 for a specific event with proper abbreviations and teams."""
        if fastf1 is None:
            return None
        try:
            race_session = fastf1.get_session(year, round_num, "R")
            race_session.load()

            # Qualifying (best effort)
            try:
                quali_session = fastf1.get_session(year, round_num, "Q")
                quali_session.load()
                quali_results = quali_session.results if hasattr(quali_session, "results") else pd.DataFrame()
            except Exception:
                quali_results = pd.DataFrame()

            # Build race results dataframe with fallback to timing
            race_results_df = None
            if hasattr(race_session, "results") and not race_session.results.empty:
                race_results_df = race_session.results.copy()
            else:
                rows = []
                for drv in race_session.drivers:
                    try:
                        laps_df = race_session.laps.pick_driver(drv)
                    except Exception:
                        laps_df = pd.DataFrame()
                    if laps_df is None or laps_df.empty or "Position" not in laps_df.columns:
                        continue
                    last_pos = laps_df["Position"].dropna().iloc[-1] if not laps_df["Position"].dropna().empty else None
                    driver_info = race_session.get_driver(drv)
                    rows.append({
                        "Abbreviation": driver_info.get("Abbreviation", str(drv)),
                        "TeamName": driver_info.get("TeamName", "Unknown"),
                        "GridPosition": driver_info.get("GridPosition", 20),
                        "Position": last_pos
                    })
                if rows:
                    race_results_df = pd.DataFrame(rows)

            if race_results_df is None or race_results_df.empty:
                return None

            if "Position" not in race_results_df.columns or race_results_df["Position"].isna().all():
                race_results_df["Position"] = range(1, len(race_results_df) + 1)

            team_alias = {
                "Red Bull Racing": "Red Bull",
                "Oracle Red Bull Racing": "Red Bull",
                "RB": "AlphaTauri",
                "Racing Bulls": "AlphaTauri",
                "Visa Cash App RB": "AlphaTauri",
                "Kick Sauber": "Sauber",
                "Stake F1 Team": "Sauber",
                "McLaren F1 Team": "McLaren",
                "Mercedes-AMG Petronas Formula One Team": "Mercedes",
                "Scuderia Ferrari": "Ferrari",
                "Aston Martin Aramco Cognizant F1 Team": "Aston Martin",
                "Alpine": "Alpine F1 Team"
            }

            rows_out = []
            # Extract weather data
            track_temp_avg = 0.0
            wind_speed_avg = 0.0
            is_wet = 0
            try:
                if hasattr(race_session, "weather_data") and race_session.weather_data is not None and not race_session.weather_data.empty:
                    wd = race_session.weather_data
                    if "TrackTemp" in wd.columns:
                        track_temp_avg = float(wd["TrackTemp"].dropna().mean()) if not wd["TrackTemp"].dropna().empty else 0.0
                    if "WindSpeed" in wd.columns:
                        wind_speed_avg = float(wd["WindSpeed"].dropna().mean()) if not wd["WindSpeed"].dropna().empty else 0.0
                    if "Rainfall" in wd.columns:
                        is_wet = 1 if wd["Rainfall"].dropna().max() > 0 else 0
            except Exception:
                pass

            for idx, driver_result in enumerate(race_results_df.reset_index(drop=True).to_dict(orient="records")):
                position = driver_result.get("Position", idx + 1)
                if pd.isna(position) or position == "" or position == 0:
                    position = idx + 1

                abbr = str(driver_result.get("Abbreviation", "")).strip()
                if not abbr:
                    try:
                        abbr = race_session.get_driver(driver_result.get("DriverNumber", "")).get("Abbreviation", "")
                    except Exception:
                        abbr = str(driver_result.get("DriverNumber", "")).strip()

                quali_pos = 20
                if not quali_results.empty:
                    dq = quali_results[quali_results["Abbreviation"] == abbr]
                    if not dq.empty:
                        quali_pos = dq["Position"].iloc[0]
                        if pd.isna(quali_pos) or quali_pos == 0:
                            quali_pos = 20

                grid_val = driver_result.get("GridPosition", 20)
                if pd.isna(grid_val) or grid_val == 0:
                    grid_val = quali_pos if not pd.isna(quali_pos) else idx + 1

                team_raw = driver_result.get("TeamName", "Unknown")
                team = team_alias.get(team_raw, team_raw)

                rows_out.append({
                    "driver_code": abbr,
                    "constructor_name": team,
                    "position": float(position),
                    "grid": float(grid_val),
                    "quali_position": float(quali_pos)
                })

            return pd.DataFrame(rows_out) if rows_out else None
        except Exception:
            return None

    def get_fastf1_races_for_year(self, year: int) -> Optional[pd.DataFrame]:
        """Get list of races for a year from FastF1 schedule."""
        if fastf1 is None:
            return None
        try:
            sched = fastf1.get_event_schedule(year)
            events = sched.loc[sched["EventName"].notna(), ["RoundNumber", "EventName", "EventDate"]].copy()
            events["EventDate"] = pd.to_datetime(events["EventDate"], errors="coerce")
            col_map = {"RoundNumber": "round", "EventName": "name", "EventDate": "date"}
            events.columns = [col_map.get(c, c) for c in events.columns]
            events["year"] = year
            df_ev = pd.DataFrame(events)
            return cast(pd.DataFrame, df_ev.loc[:, ["year", "round", "name", "date"]].copy())
        except:
            return None
    
    def load_all_fastf1_2025_races(self) -> pd.DataFrame:
        """Load all completed 2025 races from FastF1 and format for training."""
        if fastf1 is None:
            return pd.DataFrame()

        print("Loading completed 2025 races from FastF1...")
        # Try processed cache first
        cache_file = None
        try:
            processed_dir = os.path.join(os.path.dirname(__file__), ".fastf1_cache", "processed")
            os.makedirs(processed_dir, exist_ok=True)
            cache_file = os.path.join(processed_dir, "fastf1_2025_results.parquet")
            if os.path.exists(cache_file):
                df_cached = pd.read_parquet(cache_file)
                if not df_cached.empty:
                    print(f"Loaded cached FastF1 2025 results: {len(df_cached)} rows")
                    return df_cached
        except Exception:
            cache_file = None
            pass
        try:
            sched = fastf1.get_event_schedule(2025)
            events = sched.loc[sched["EventName"].notna()].copy()
            events["EventDate"] = pd.to_datetime(events["EventDate"], errors="coerce")
            today = pd.Timestamp.today(tz=None)
            completed = events[events["EventDate"] < today]

            all_results = []
            for _, event in completed.iterrows():
                round_num = int(event["RoundNumber"])
                event_name = str(event["EventName"])
                event_date = event["EventDate"]

                try:
                    race_session = fastf1.get_session(2025, round_num, "R")
                    race_session.load()
                except Exception as e:
                    print(f"  Skipped: {event_name} (Round {round_num}) - failed to load race: {e}")
                    continue

                # Qualifying session (best effort)
                try:
                    quali_session = fastf1.get_session(2025, round_num, "Q")
                    quali_session.load()
                    quali_results = quali_session.results if hasattr(quali_session, "results") else pd.DataFrame()
                except Exception:
                    quali_results = pd.DataFrame()

                # Process race results with fallback to timing data
                race_results_df = None
                if hasattr(race_session, "results") and not race_session.results.empty:
                    race_results_df = race_session.results.copy()
                else:
                    rows = []
                    for drv in race_session.drivers:
                        try:
                            laps_df = race_session.laps.pick_driver(drv)
                        except Exception:
                            laps_df = pd.DataFrame()
                        if laps_df is None or laps_df.empty or "Position" not in laps_df.columns:
                            continue
                        last_pos = laps_df["Position"].dropna().iloc[-1] if not laps_df["Position"].dropna().empty else None
                        driver_info = race_session.get_driver(drv)
                        rows.append({
                            "Abbreviation": driver_info.get("Abbreviation", ""),
                            "TeamName": driver_info.get("TeamName", "Unknown"),
                            "GridPosition": driver_info.get("GridPosition", 20),
                            "Position": last_pos
                        })
                    if rows:
                        race_results_df = pd.DataFrame(rows)

                if race_results_df is None or race_results_df.empty:
                    print(f"  WARNING: No results data for {event_name}")
                    continue

                if "Position" not in race_results_df.columns or race_results_df["Position"].isna().all():
                    race_results_df["Position"] = range(1, len(race_results_df) + 1)

                # Extract weather data for this race
                track_temp_avg = 0.0
                wind_speed_avg = 0.0
                is_wet = 0
                try:
                    if hasattr(race_session, "weather_data") and race_session.weather_data is not None and not race_session.weather_data.empty:
                        wd = race_session.weather_data
                        if "TrackTemp" in wd.columns:
                            track_temp_avg = float(wd["TrackTemp"].dropna().mean()) if not wd["TrackTemp"].dropna().empty else 0.0
                        if "WindSpeed" in wd.columns:
                            wind_speed_avg = float(wd["WindSpeed"].dropna().mean()) if not wd["WindSpeed"].dropna().empty else 0.0
                        if "Rainfall" in wd.columns:
                            is_wet = 1 if wd["Rainfall"].dropna().max() > 0 else 0
                except Exception:
                    pass

                matched_count = 0
                team_alias = {
                    "Red Bull Racing": "Red Bull",
                    "Oracle Red Bull Racing": "Red Bull",
                    "RB": "AlphaTauri",
                    "Visa Cash App RB": "AlphaTauri",
                    "Racing Bulls": "AlphaTauri",
                    "Kick Sauber": "Sauber",
                    "Stake F1 Team": "Sauber",
                    "McLaren F1 Team": "McLaren",
                    "Mercedes-AMG Petronas Formula One Team": "Mercedes",
                    "Scuderia Ferrari": "Ferrari",
                    "Aston Martin Aramco Cognizant F1 Team": "Aston Martin",
                    "Alpine": "Alpine F1 Team"
                }

                for idx, driver_result in enumerate(race_results_df.reset_index(drop=True).to_dict(orient="records")):
                    position = driver_result.get("Position", idx + 1)
                    if pd.isna(position) or position == "" or position == 0:
                        position = idx + 1

                    driver_abbr = str(driver_result.get("Abbreviation", "")).strip()

                    quali_pos = 20
                    if not quali_results.empty:
                        driver_quali = quali_results[quali_results["Abbreviation"] == driver_abbr]
                        if not driver_quali.empty:
                            quali_pos = driver_quali["Position"].iloc[0]
                            if pd.isna(quali_pos) or quali_pos == 0:
                                quali_pos = 20

                    grid_val = driver_result.get("GridPosition", 20)
                    if pd.isna(grid_val) or grid_val == 0:
                        grid_val = quali_pos if not pd.isna(quali_pos) else idx + 1

                    driver_match = self.drivers[self.drivers["driver_code"] == driver_abbr]
                    if driver_match.empty:
                        new_driver_id = 10000 + len(self.drivers) + 1
                        self.drivers = pd.concat([
                            self.drivers,
                            pd.DataFrame([{ "driverId": new_driver_id, "driver_code": driver_abbr, "surname": driver_abbr }])
                        ], ignore_index=True)
                        driver_id = new_driver_id
                    else:
                        driver_id = driver_match["driverId"].iloc[0]

                    team_name_raw = driver_result.get("TeamName", "Unknown")
                    team_name = team_alias.get(team_name_raw, team_name_raw)
                    constructor_match = self.constructors[self.constructors["constructor_name"] == team_name]
                    if constructor_match.empty:
                        new_cons_id = 10000 + len(self.constructors) + 1
                        self.constructors = pd.concat([
                            self.constructors,
                            pd.DataFrame([{ "constructorId": new_cons_id, "constructor_name": team_name }])
                        ], ignore_index=True)
                        constructor_id = new_cons_id
                    else:
                        constructor_id = constructor_match["constructorId"].iloc[0]

                    matched_count += 1
                    all_results.append({
                        "driverId": driver_id,
                        "driver_code": driver_abbr,
                        "constructorId": constructor_id,
                        "constructor_name": team_name,
                        "position": float(position),
                        "grid": float(grid_val),
                        "quali_position": float(quali_pos),
                        "points": 0,
                        "date": event_date,
                        "year": 2025,
                        "round": round_num,
                        "circuitId": 0,
                        "qual_time_seconds": None,
                        "TrackTempAvg": track_temp_avg,
                        "WindSpeedAvg": wind_speed_avg,
                        "IsWet": is_wet
                    })

                if matched_count > 0:
                    print(f"  Loaded: {event_name} (Round {round_num}) - {matched_count} drivers")
                else:
                    print(f"  WARNING: No drivers matched for {event_name} - check driver codes/team names")

            if all_results:
                df_2025 = pd.DataFrame(all_results)
                points_map = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
                df_2025["points"] = df_2025["position"].map(lambda p: points_map.get(int(p), 0) if p <= 10 else 0)
                print(f"Loaded {len(df_2025)} results from {len(completed)} completed 2025 races")
                # Save processed cache
                try:
                    if cache_file:
                        df_2025.to_parquet(cache_file, index=False)
                        print(f"Cached FastF1 2025 processed results to {cache_file}")
                except Exception:
                    pass
                return df_2025
            else:
                print("No 2025 race results loaded")
                return pd.DataFrame()
        except Exception as e:
            import traceback
            print(f"Failed to load 2025 FastF1 data: {e}")
            traceback.print_exc()
            return pd.DataFrame()

    def get_data(self) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """Return all loaded data."""
        return (
            pd.DataFrame(self.results),
            pd.DataFrame(self.races),
            pd.DataFrame(self.qualifying),
            pd.DataFrame(self.drivers),
            pd.DataFrame(self.constructors),
        )
