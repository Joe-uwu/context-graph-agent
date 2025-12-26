#!/usr/bin/env python
"""
Optimized F1 Prediction Script - Direct Backend Testing
No frontend, just direct race predictions with proper output
"""

import sys
import pandas as pd
from data_loader import F1DataLoader, fastf1
from f1_model import F1Predictor, PredictorCalibrator, print_calibration_report, save_calibration_report

def print_header(text):
    """Print formatted header"""
    print("\n" + "="*70)
    print(text)
    print("="*70)

def predict_past_race(predictor, results, races, loader):
    """Predict a past race with user input"""
    print_header("PAST RACE PREDICTION")
    
    # Get year
    year = input("\nEnter year (1950-2025, default 2025): ").strip()
    year = int(year) if year else 2025
    
    # Get races for that year
    year_races = races[races['year'] == year].sort_values('round')
    
    # If no races in historical data (e.g., 2025), try FastF1
    if year_races.empty and year >= 2025:
        print(f"No Kaggle data for {year}, attempting FastF1 fallback...")
        if fastf1 is not None:
            try:
                sched = fastf1.get_event_schedule(year)
                sched = sched[sched["EventName"].notna()].copy()
                sched["date"] = pd.to_datetime(sched["EventDate"], errors="coerce")
                sched["round"] = sched["RoundNumber"].astype(int)
                sched["year"] = year
                year_races = sched[["year", "round", "EventName", "date"]].rename(columns={"EventName": "name"})
            except Exception:
                year_races = loader.get_fastf1_races_for_year(year)
        else:
            year_races = loader.get_fastf1_races_for_year(year)
        if year_races is None or year_races.empty:
            print(f"No race data available for year {year}")
            return
        # Filter to completed races only
        today = pd.Timestamp.today(tz=None)
        year_races = year_races[year_races['date'] < today]
        if year_races.empty:
            print(f"No completed races found for {year} yet")
            return
    
        if year_races.empty:
            print(f"No races found for year {year}")
            return

    name_lookup = {}
    # Ensure race names are populated for FastF1 fallback listings
    if fastf1 is not None and year >= 2025:
        try:
            sched = fastf1.get_event_schedule(year)
            sched = sched[sched["EventName"].notna()].copy()
            sched["round"] = sched["RoundNumber"].astype(int)
            name_lookup = sched.set_index("round")["EventName"].to_dict()

            year_races = year_races.copy()
            year_races["name"] = year_races["round"].map(name_lookup).combine_first(year_races.get("name"))
            numeric_name_mask = year_races["name"].astype(str).str.fullmatch(r"\d+")
            if numeric_name_mask.all():
                # If everything is still numeric, rebuild from schedule directly
                sched = loader.get_fastf1_races_for_year(year)
                if sched is not None and not sched.empty:
                    sched = sched[sched["date"] < pd.Timestamp.today(tz=None)]
                    year_races = sched.sort_values("round").reset_index(drop=True)
            else:
                if numeric_name_mask.any():
                    year_races.loc[numeric_name_mask, "name"] = year_races.loc[numeric_name_mask, "round"].map(name_lookup)
                year_races["name"] = year_races["name"].astype(str)
                year_races = year_races.sort_values("round").reset_index(drop=True)
        except Exception:
            pass
    
    print(f"\nFound {len(year_races)} races for {year}:")
    print("\nRound | Grand Prix Name")
    print("-" * 50)
    for _, race in year_races.iterrows():
        round_num = int(race['round'])
        race_name = name_lookup.get(round_num) or (str(race['name']) if pd.notna(race['name']) else f"Round {round_num}")
        print(f"{round_num:3d}   | {race_name}")
    
    # Get race selection
    round_choice = input(f"\nSelect round number (1-{len(year_races)}): ").strip()
    if not round_choice:
        print("No selection made")
        return
    
    round_num = int(round_choice)
    selected = year_races[year_races['round'] == round_num]
    
    if selected.empty:
        print(f"Round {round_num} not found")
        return
    
    race_id = int(selected.iloc[0]['raceId']) if 'raceId' in selected.columns else None
    race_name = selected.iloc[0]['name']
    event_date = pd.to_datetime(selected.iloc[0]['date']) if 'date' in selected.columns else None
    
    print(f"\nPredicting: {race_name} ({year})")
    print("Loading race data...")
    
    # Get race results (from historical data or FastF1)
    if race_id is not None:
        race_results = results[results['raceId'] == race_id]
    else:
        # FastF1 fallback for 2025
        race_results = loader.get_fastf1_race_results(year, round_num)
        if race_results is None or race_results.empty:
            print(f"No data available for this race")
            return
    
    if race_results.empty:
        print(f"No data available for this race")
        return
    
    driver_codes = race_results['driver_code'].unique().tolist()
    print(f"Found {len(driver_codes)} drivers in race")
    
    # Get qualifying positions
    quali_positions = {}
    if 'quali_position' in race_results.columns:
        for code in driver_codes:
            qual = race_results[race_results['driver_code'] == code]['quali_position'].dropna()
            if not qual.empty:
                quali_positions[code] = float(qual.iloc[0])
            else:
                grid = race_results[race_results['driver_code'] == code]['grid'].fillna(10).mean()
                quali_positions[code] = float(grid)
    else:
        # FastF1 data: use grid positions
        for code in driver_codes:
            grid = race_results[race_results['driver_code'] == code]['grid'].fillna(10).mean()
            quali_positions[code] = float(grid)
    
    # Get constructor mapping
    if 'constructor_name' in race_results.columns:
        constructor_mapping = race_results.set_index('driver_code')['constructor_name'].to_dict()
    else:
        constructor_mapping = race_results.set_index('driver_code')['team_name'].to_dict()
    
    # Generate predictions
    print("Generating predictions...")
    predictions = predictor.predict_race(
        driver_codes=driver_codes,
        quali_positions=quali_positions,
        constructor_ids=constructor_mapping,
        circuit_id=0,
        as_of_date=event_date
    )
    
    if predictions.empty:
        print("Could not generate predictions")
        return
    
    # Display results
    print_header(f"PREDICTIONS: {race_name} ({year})")
    print("\n{:3s} | {:4s} | {:20s} | {:>12s}".format("Pos", "Code", "Constructor", "Win Prob"))
    print("-" * 50)
    
    for i, (_, row) in enumerate(predictions.head(10).iterrows(), 1):
        driver = row['driver_code']
        team = row['constructor_name'][:20]
        prob = row['win_probability']
        print(f"{i:3d} | {driver:4s} | {team:20s} | {prob:11.2f}%")
    
    # Show actual winner if available
    actual_winner = race_results[race_results['position'] == 1]
    if not actual_winner.empty:
        winner_code = actual_winner.iloc[0]['driver_code']
        print(f"\nActual Winner: {winner_code}")

def quick_test(predictor, results):
    """Quick test with Bahrain 2024"""
    print_header("QUICK TEST: Bahrain Grand Prix 2024")
    
    # Find Bahrain 2024
    race_results = results[(results['raceId'] == 1101)]  # Bahrain 2024 race ID
    
    if race_results.empty:
        print("Bahrain 2024 data not available")
        return
    
    driver_codes = race_results['driver_code'].unique().tolist()
    
    # Get qualifying and constructors
    quali_positions = {}
    for code in driver_codes:
        qual = race_results[race_results['driver_code'] == code]['quali_position'].dropna()
        quali_positions[code] = float(qual.iloc[0]) if not qual.empty else 10.0
    
    constructor_mapping = race_results.set_index('driver_code')['constructor_name'].to_dict()
    
    # Predict
    predictions = predictor.predict_race(
        driver_codes=driver_codes,
        quali_positions=quali_positions,
        constructor_ids=constructor_mapping,
        as_of_year=2024,
        as_of_round=1
    )
    
    print("\n{:3s} | {:4s} | {:20s} | {:>12s}".format("Pos", "Code", "Constructor", "Win Prob"))
    print("-" * 50)
    
    for i, (_, row) in enumerate(predictions.head(10).iterrows(), 1):
        driver = row['driver_code']
        team = row['constructor_name'][:20]
        prob = row['win_probability']
        print(f"{i:3d} | {driver:4s} | {team:20s} | {prob:11.2f}%")

def predict_upcoming_race(predictor, loader):
    """Predict the next upcoming race for 2026 using FastF1. If schedule is unavailable, exit."""
    print_header("UPCOMING RACE PREDICTION (FastF1)")

    year_in = input("\nEnter upcoming race year (default 2026): ").strip()
    year = int(year_in) if year_in else 2026
    
    current_year = pd.Timestamp.today().year
    if year < current_year:
        print(f"Cannot predict upcoming race for past year {year}. Use 'Predict Past Race' instead.")
        return

    if fastf1 is None:
        print("FastF1 not available")
        return

    try:
        sched = fastf1.get_event_schedule(year)
        events = sched.loc[sched["EventName"].notna(), ["RoundNumber", "EventName", "EventDate"]].copy()
        events["EventDate"] = pd.to_datetime(events["EventDate"], errors="coerce")
        today = pd.Timestamp.today(tz=None)
        upcoming = events[events["EventDate"] >= today].sort_values("EventDate")
        if upcoming.empty:
            print("The schedule for the new season is not available yet")
            return
        next_event = upcoming.iloc[0]
        round_num = int(next_event["RoundNumber"])
        race_name = str(next_event["EventName"])
    except Exception:
        print("The schedule for the new season is not available yet")
        return

    session_info = loader.get_current_session_info(year=year, round_num=round_num)
    if session_info is None:
        print("The schedule for the new season is not available yet")
        return
    grid_df = pd.DataFrame(session_info["drivers"]) if session_info else loader.get_current_grid()
    event_date = session_info.get("event_date")
    print(f"Fetched {len(grid_df)} drivers from FastF1")

    driver_codes = grid_df["driver_code"].tolist()

    quali_data = loader.get_live_qualifying(year=year, round_num=round_num)
    if quali_data is not None and not quali_data.empty:
        quali_positions = quali_data.set_index("driver_code")["quali_position"].to_dict()
    else:
        quali_positions = {code: i + 1 for i, code in enumerate(driver_codes)}

    constructor_mapping = grid_df.set_index("driver_code")["team_name"].to_dict()

    print("Generating predictions...")
    predictions = predictor.predict_race(
        driver_codes=driver_codes,
        quali_positions=quali_positions,
        constructor_ids=constructor_mapping,
        circuit_id=0,
        as_of_date=event_date
    )

    if predictions.empty:
        print("Could not generate predictions")
        return

    print_header(f"PREDICTIONS: {race_name} ({year})")
    print("\n{:3s} | {:4s} | {:20s} | {:>12s}".format("Pos", "Code", "Constructor", "Win Prob"))
    print("-" * 50)
    for i, (_, row) in enumerate(predictions.head(10).iterrows(), 1):
        driver = row['driver_code']
        team = row['constructor_name'][:20]
        prob = row['win_probability']
        print(f"{i:3d} | {driver:4s} | {team:20s} | {prob:11.2f}%")

def calibrate_model(predictor):
    """Calibrate prediction model parameters using historical races."""
    print_header("PARAMETER CALIBRATION")
    
    calibrator = PredictorCalibrator(predictor)
    
    years_input = input("\nEnter starting year for calibration (default 2022): ").strip()
    min_year = int(years_input) if years_input else 2022
    
    races_input = input("Enter max number of races to use (default 50): ").strip()
    max_races = int(races_input) if races_input else 50
    
    print("\nStarting parameter optimization...")
    print("This may take 1-2 minutes. The model will try different parameter combinations")
    print("to maximize accuracy on past race predictions.\n")
    
    optimal_config = calibrator.calibrate(min_year=min_year, max_races=max_races, method='differential_evolution')
    
    # Apply new config
    predictor.config = optimal_config
    
    print("\n✓ Model parameters updated!")
    print(f"New configuration:")
    print(f"  grid_alpha={optimal_config.grid_alpha:.3f}")
    print(f"  form_boost_weight={optimal_config.form_boost_weight:.3f}")
    print(f"  temperature={optimal_config.temperature:.3f}")

def main():
    print_header("F1 RACE WINNER PREDICTOR - OPTIMIZED")
    
    # Load data
    print("\n[1/3] Loading historical F1 data...")
    loader = F1DataLoader(min_year=2010, max_year=2025)
    results, races, _, drivers, constructors = loader.get_data()
    print(f"Loaded {len(drivers)} drivers, {len(constructors)} constructors, {len(races)} races")
    
    # Load 2025 FastF1 data and add to training set
    print("\n[1.5/3] Loading 2025 completed races from FastF1...")
    fastf1_2025 = loader.load_all_fastf1_2025_races()
    if not fastf1_2025.empty:
        results = pd.concat([results, fastf1_2025], ignore_index=True)
        print(f"Added {len(fastf1_2025)} 2025 results to training data")
    
    # Train model
    print("\n[2/3] Training prediction model...")
    predictor = F1Predictor(results, drivers, constructors)
    print("Model trained successfully")
    
    # Main menu
    print("\n[3/3] Ready for predictions!")
    
    while True:
        print_header("MAIN MENU")
        print("\n1. Predict Past Race (select year & GP)")
        print("2. Quick Test (Bahrain 2024)")
        print("3. Predict Next Upcoming Race (FastF1, default 2026)")
        print("4. Calibrate Model Parameters (learn from past races)")
        print("5. Show Calibration Report (from last calibration)")
        print("6. Save Calibration Report (save to CALIBRATION_REPORT.md)")
        print("7. Exit")
        
        choice = input("\nSelect option (1-7): ").strip()
        
        if choice == "1":
            predict_past_race(predictor, results, races, loader)
        elif choice == "2":
            quick_test(predictor, results)
        elif choice == "3":
            predict_upcoming_race(predictor, loader)
        elif choice == "4":
            calibrate_model(predictor)
        elif choice == "5":
            print_header("CALIBRATION REPORT")
            print_calibration_report()
        elif choice == "6":
            save_calibration_report()
        elif choice == "7":
            print("\nGoodbye!")
            break
        else:
            print("Invalid choice")
        
        input("\n\nPress Enter to continue...")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
