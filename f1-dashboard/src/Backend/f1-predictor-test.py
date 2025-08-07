import pandas as pd
import numpy as np
import requests
import time
import os
from datetime import datetime, timezone
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
from sklearn.preprocessing import RobustScaler
import warnings

# Suppress common warnings for a cleaner output
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.filterwarnings('ignore', category=pd.errors.PerformanceWarning)

class F1Predictor:
    BASE_URL = "https://api.openf1.org/v1"

    def __init__(self):
        """
        Initializes the F1Predictor class using the OpenF1 API for all data.
        """
        self.api_key = os.getenv("OPENF1_API_KEY")
        if self.api_key:
            print("API key found. Using authenticated session.")
        else:
            print("API key not found. Using rate-limited session with exponential backoff.")

        self.current_year = datetime.now().year
        self._driver_cache = {}
        self._team_cache = {}

        print("Fetching current season schedule...")
        self.schedule = self.get_schedule(self.current_year)
        
        print("Calculating current season standings... (This may take a moment)")
        self.driver_standings, self.constructor_standings = self._calculate_standings(self.current_year)
        
        self.active_drivers = self.get_active_drivers()

    def _api_call(self, endpoint, retries=6, backoff_factor=3):
        """
        Helper function to make API calls to OpenF1 with a more aggressive backoff.
        """
        headers = {}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        for i in range(retries):
            try:
                response = requests.get(f"{self.BASE_URL}/{endpoint}", headers=headers)
                response.raise_for_status()
                if not self.api_key:
                    time.sleep(0.5) # A base delay for non-authenticated requests
                return response.json()
            except requests.exceptions.HTTPError as e:
                # Only retry on rate limit if we DON'T have a key
                if e.response.status_code == 429 and not self.api_key:
                    wait_time = backoff_factor * (2 ** i) 
                    print(f"Rate limit hit. Retrying in {wait_time:.2f} seconds...")
                    time.sleep(wait_time)
                    continue
                print(f"API call failed for endpoint '{endpoint}': {e}")
                return None
            except requests.exceptions.RequestException as e:
                print(f"API call failed for endpoint '{endpoint}': {e}")
                return None
        
        print(f"API call failed for endpoint '{endpoint}' after {retries} retries.")
        return None

    def get_schedule(self, year):
        """Retrieves the race schedule for a given year using OpenF1."""
        data = self._api_call(f"meetings?year={year}")
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        df.rename(columns={
            'meeting_name': 'EventName',
            'date_start': 'EventDate',
            'circuit_short_name': 'CircuitId'
        }, inplace=True)
        df['EventDate'] = pd.to_datetime(df['EventDate'])
        return df

    def _get_latest_session_key(self, year):
        """Gets the session_key for the last completed race of a given year."""
        schedule_df = self.get_schedule(year)
        if schedule_df.empty:
            return None
            
        now_utc = datetime.now(timezone.utc)
            
        completed_races = schedule_df[schedule_df['EventDate'] < now_utc].copy()
        if completed_races.empty:
            return None

        latest_meeting_key = completed_races.sort_values(by='EventDate', ascending=False).iloc[0]['meeting_key']
        
        sessions = self._api_call(f"sessions?meeting_key={latest_meeting_key}&session_name=Race")
        if sessions:
            return sessions[0]['session_key']
        return None

    def _calculate_standings(self, year):
        """Calculates driver and constructor standings using OpenF1."""
        latest_session_key = self._get_latest_session_key(year)
        if not latest_session_key:
            return pd.DataFrame(), pd.DataFrame()

        driver_data = self._api_call(f"driver_standings?session_key={latest_session_key}")
        if not driver_data:
            driver_standings_df = pd.DataFrame()
        else:
            driver_standings_df = pd.DataFrame(driver_data)
            drivers_info = self._get_drivers_for_session(latest_session_key)
            driver_standings_df = driver_standings_df.merge(drivers_info, on='driver_number')
            driver_standings_df.rename(columns={
                'full_name': 'DriverId', 
                'team_name': 'ConstructorId',
                'points': 'Points', 
                'wins': 'Wins'
            }, inplace=True)
            driver_standings_df = driver_standings_df[['DriverId', 'ConstructorId', 'Points', 'Wins']]

        constructor_data = self._api_call(f"team_standings?session_key={latest_session_key}")
        if not constructor_data:
            constructor_standings_df = pd.DataFrame()
        else:
            constructor_standings_df = pd.DataFrame(constructor_data)
            constructor_standings_df.rename(columns={
                'team_name': 'ConstructorId',
                'points': 'ConstructorPoints',
                'wins': 'ConstructorWins'
            }, inplace=True)
            constructor_standings_df = constructor_standings_df[['ConstructorId', 'ConstructorPoints', 'ConstructorWins']]

        return driver_standings_df, constructor_standings_df

    def _get_drivers_for_session(self, session_key):
        """Helper to get and cache driver details for a session."""
        if session_key in self._driver_cache:
            return self._driver_cache[session_key]
        
        drivers_data = self._api_call(f"drivers?session_key={session_key}")
        if not drivers_data:
            return pd.DataFrame()
        
        df = pd.DataFrame(drivers_data)
        self._driver_cache[session_key] = df
        return df

    def get_active_drivers(self):
        """Retrieves the list of active drivers from the current standings."""
        if not self.driver_standings.empty:
            active_drivers_df = self.driver_standings[['DriverId']].copy()
            active_drivers_df.rename(columns={'DriverId': 'Driver'}, inplace=True)
            active_drivers_df['DriverId'] = active_drivers_df['Driver']
            return active_drivers_df
        return pd.DataFrame()

    def get_historical_race_results(self, circuit_id_filter=None):
        """Retrieves historical race results for the past 5 years using OpenF1."""
        all_results = []
        for year in range(self.current_year - 5, self.current_year):
            print(f"Fetching historical data for {year}...")
            schedule = self.get_schedule(year)
            if schedule.empty:
                continue
            if circuit_id_filter:
                schedule = schedule[schedule['CircuitId'] == circuit_id_filter]

            for _, race in schedule.iterrows():
                sessions = self._api_call(f"sessions?meeting_key={race['meeting_key']}&session_name=Race")
                if not sessions:
                    continue
                
                session_key = sessions[0]['session_key']
                results_data = self._api_call(f"results?session_key={session_key}")
                if not results_data:
                    continue
                
                drivers_info = self._get_drivers_for_session(session_key)
                if drivers_info.empty:
                    continue

                results_df = pd.DataFrame(results_data)
                results_df = results_df.merge(drivers_info, on='driver_number')
                
                for _, res in results_df.iterrows():
                    all_results.append({
                        'Year': year,
                        'RaceName': race['EventName'],
                        'CircuitId': race['CircuitId'],
                        'RaceDate': race['EventDate'].date(),
                        'DriverId': res['full_name'],
                        'ConstructorId': res['team_name'],
                        'GridPosition': int(res['starting_grid_position']) if pd.notnull(res['starting_grid_position']) else 0,
                        'FinishPosition': int(res['position']) if pd.notnull(res['position']) else 0,
                        'Points': float(res['points']) if pd.notnull(res['points']) else 0,
                    })
        return pd.DataFrame(all_results)

    def get_qualifying_results(self, grand_prix_name, year):
        """Retrieves qualifying results from OpenF1."""
        schedule = self.get_schedule(year)
        meeting = schedule[schedule['EventName'].str.contains(grand_prix_name, case=False, na=False)]
        if meeting.empty:
            return pd.DataFrame()
        meeting_key = meeting.iloc[0]['meeting_key']

        session_types = ['Qualifying', 'Sprint Qualifying', 'Practice 3', 'Practice 2']
        session_key = None
        for s_type in session_types:
            session_data = self._api_call(f"sessions?meeting_key={meeting_key}&session_name={s_type}")
            if session_data:
                session_key = session_data[0]['session_key']
                print(f"Loaded data from session: {s_type}")
                break
        
        if not session_key:
            return pd.DataFrame()
        
        results_data = self._api_call(f"results?session_key={session_key}")
        if not results_data:
            return pd.DataFrame()
        
        drivers_info = self._get_drivers_for_session(session_key)
        results_df = pd.DataFrame(results_data).merge(drivers_info, on='driver_number')
        
        qualifying_results = results_df[['full_name', 'position']].copy()
        qualifying_results.rename(columns={'full_name': 'DriverId', 'position': 'QualifyingPosition'}, inplace=True)
        qualifying_results = qualifying_results.dropna(subset=['DriverId', 'QualifyingPosition'])
        qualifying_results['QualifyingPosition'] = qualifying_results['QualifyingPosition'].astype(int)
        
        return qualifying_results

    def get_circuit_id(self, track_name, year):
        """Maps a Grand Prix name to its corresponding circuitId."""
        schedule = self.get_schedule(year)
        if not schedule.empty:
            mask = schedule['EventName'].str.contains(track_name, case=False, na=False)
            if mask.any():
                return schedule.loc[mask].iloc[0]['CircuitId']
        clean_name = track_name.lower().replace('grand prix', '').strip()
        return clean_name.replace(" ", "_")

    def get_circuit_features(self, circuit_id):
        circuit_features = {
            'bahrain': {'CircuitType': 'Permanent', 'CircuitLength': 5.412}, 'jeddah': {'CircuitType': 'Street', 'CircuitLength': 6.174},
            'albert_park': {'CircuitType': 'Street', 'CircuitLength': 5.278}, 'baku': {'CircuitType': 'Street', 'CircuitLength': 6.003},
            'miami': {'CircuitType': 'Street', 'CircuitLength': 5.412}, 'monaco': {'CircuitType': 'Street', 'CircuitLength': 3.337},
            'catalunya': {'CircuitType': 'Permanent', 'CircuitLength': 4.655}, 'villeneuve': {'CircuitType': 'Street', 'CircuitLength': 4.361},
            'red_bull_ring': {'CircuitType': 'Permanent', 'CircuitLength': 4.318}, 'silverstone': {'CircuitType': 'Permanent', 'CircuitLength': 5.891},
            'hungaroring': {'CircuitType': 'Permanent', 'CircuitLength': 4.381}, 'spa-francorchamps': {'CircuitType': 'Permanent', 'CircuitLength': 7.004},
            'zandvoort': {'CircuitType': 'Permanent', 'CircuitLength': 4.259}, 'monza': {'CircuitType': 'Permanent', 'CircuitLength': 5.793},
            'marina_bay': {'CircuitType': 'Street', 'CircuitLength': 5.063}, 'suzuka': {'CircuitType': 'Permanent', 'CircuitLength': 5.807},
            'losail': {'CircuitType': 'Permanent', 'CircuitLength': 5.380}, 'americas': {'CircuitType': 'Permanent', 'CircuitLength': 5.513},
            'hermanos_rodriguez': {'CircuitType': 'Permanent', 'CircuitLength': 4.304}, 'interlagos': {'CircuitType': 'Permanent', 'CircuitLength': 4.309},
            'las_vegas': {'CircuitType': 'Street', 'CircuitLength': 6.120}, 'yas_marina': {'CircuitType': 'Permanent', 'CircuitLength': 5.554},
        }
        return circuit_features.get(circuit_id, {'CircuitType': 'Unknown', 'CircuitLength': 5.0})

    def prepare_historical_data(self):
        historical_results = self.get_historical_race_results()
        if historical_results is None or historical_results.empty:
            return None

        historical_results['RaceDate'] = pd.to_datetime(historical_results['RaceDate'])
        historical_results['Win'] = (historical_results['FinishPosition'] == 1).astype(int)

        historical_results.sort_values(['DriverId', 'RaceDate'], inplace=True)
        historical_results['CumulativePoints'] = historical_results.groupby('DriverId')['Points'].cumsum() - historical_results['Points']
        historical_results['CumulativeWins'] = historical_results.groupby('DriverId')['Win'].cumsum() - historical_results['Win']

        historical_results['ConstructorWin'] = (historical_results['FinishPosition'] == 1).astype(int)
        historical_results['ConstructorCumulativePoints'] = historical_results.groupby('ConstructorId')['Points'].cumsum() - historical_results['Points']
        historical_results['ConstructorCumulativeWins'] = historical_results.groupby('ConstructorId')['ConstructorWin'].cumsum() - historical_results['ConstructorWin']

        historical_results['AvgPointsLast5'] = historical_results.groupby('DriverId')['Points'].rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True).fillna(0)
        historical_results['AvgFinishPositionLast5'] = historical_results.groupby('DriverId')['FinishPosition'].rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True).fillna(0)
        historical_results['WinsLast5'] = historical_results.groupby('DriverId')['Win'].rolling(window=5, min_periods=1).sum().shift(1).reset_index(level=0, drop=True).fillna(0)
        
        if self.active_drivers is not None and not self.active_drivers.empty:
            active_driver_ids = self.active_drivers['DriverId'].unique()
            historical_results = historical_results[historical_results['DriverId'].isin(active_driver_ids)]

        return historical_results

    def calculate_circuit_stats(self, circuit_id, historical_data):
        circuit_results = historical_data[historical_data['CircuitId'] == circuit_id]
        if circuit_results.empty:
            return pd.DataFrame()

        circuit_stats = circuit_results.groupby('DriverId').agg(
            AvgFinishPositionCircuit=('FinishPosition', 'mean'),
            BestFinishPositionCircuit=('FinishPosition', 'min'),
            TotalPointsCircuit=('Points', 'sum'),
            WinsCircuit=('Win', 'sum'),
            RacesAtCircuit=('RaceDate', 'count')
        ).reset_index()
        circuit_stats['WinRateCircuit'] = circuit_stats['WinsCircuit'] / circuit_stats['RacesAtCircuit']
        return circuit_stats

    def prepare_features(self, historical_data, circuit_stats, grand_prix_name, race_year):
        qualifying_results = self.get_qualifying_results(grand_prix_name, race_year)

        if not qualifying_results.empty:
            drivers_in_race = qualifying_results['DriverId'].unique()
        else:
            print(f"No entry list available for {grand_prix_name} {race_year}. Proceeding with all active drivers.")
            drivers_in_race = self.active_drivers['DriverId'].unique() if not self.active_drivers.empty else []

        data = self.driver_standings[self.driver_standings['DriverId'].isin(drivers_in_race)].copy()
        data = data.merge(self.constructor_standings, on='ConstructorId', how='left', suffixes=('', '_const'))
        data = data.merge(circuit_stats, on='DriverId', how='left')

        if not qualifying_results.empty:
            data = data.merge(qualifying_results, on='DriverId', how='left')
        else:
            avg_grid_positions = historical_data.groupby('DriverId')['GridPosition'].mean().reset_index()
            avg_grid_positions.rename(columns={'GridPosition': 'QualifyingPosition'}, inplace=True)
            data = data.merge(avg_grid_positions, on='DriverId', how='left')
        
        historical_data['AvgQualifyingPositionLast5'] = historical_data.groupby('DriverId')['GridPosition'].rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True).fillna(historical_data['GridPosition'].mean())
        
        if not historical_data.empty:
            most_recent_date = historical_data['RaceDate'].max()
            recent_performance = historical_data[historical_data['RaceDate'] == most_recent_date][['DriverId', 'AvgPointsLast5', 'AvgFinishPositionLast5', 'WinsLast5', 'AvgQualifyingPositionLast5']]
            data = data.merge(recent_performance, on='DriverId', how='left')
        
        data.fillna(0, inplace=True)

        circuit_features_data = self.get_circuit_features(self.get_circuit_id(grand_prix_name, race_year))
        data['CircuitType'] = circuit_features_data['CircuitType']
        data['CircuitLength'] = circuit_features_data['CircuitLength']
        data['CircuitType'] = data['CircuitType'].map({'Permanent': 0, 'Street': 1, 'Unknown': 2})

        feature_columns = [
            'QualifyingPosition', 'Wins', 'Points', 'ConstructorPoints', 'ConstructorWins', 'AvgFinishPositionCircuit',
            'BestFinishPositionCircuit', 'TotalPointsCircuit', 'WinsCircuit', 'WinRateCircuit', 'AvgPointsLast5',
            'AvgFinishPositionLast5', 'WinsLast5', 'AvgQualifyingPositionLast5', 'CircuitType', 'CircuitLength',
        ]
        
        for col in feature_columns:
            if col not in data.columns:
                data[col] = 0
        features = data[feature_columns]

        historical_data['CircuitType'] = historical_data['CircuitId'].apply(lambda x: self.get_circuit_features(x)['CircuitType']).map({'Permanent': 0, 'Street': 1, 'Unknown': 2})
        historical_data['CircuitLength'] = historical_data['CircuitId'].apply(lambda x: self.get_circuit_features(x)['CircuitLength'])
        historical_data = historical_data.merge(circuit_stats, on='DriverId', how='left', suffixes=('', '_circ'))
        historical_data.fillna(0, inplace=True)
        
        historical_data['Points'] = historical_data['CumulativePoints']
        historical_data['Wins'] = historical_data['CumulativeWins']
        historical_data['ConstructorPoints'] = historical_data['ConstructorCumulativePoints']
        historical_data['ConstructorWins'] = historical_data['ConstructorCumulativeWins']
        historical_data['QualifyingPosition'] = historical_data['GridPosition']

        for col in feature_columns:
            if col not in historical_data.columns:
                 historical_data[col] = 0
        historical_features = historical_data[feature_columns]

        return features, data, historical_features, feature_columns

    def train_model(self, historical_features, target, feature_columns):
        historical_features = historical_features.replace([np.inf, -np.inf], np.nan).fillna(0)
        scaler = RobustScaler()
        historical_features_scaled = scaler.fit_transform(historical_features)
        
        sm = SMOTE(random_state=42)
        X_res, y_res = sm.fit_resample(historical_features_scaled, target)
        
        X_train, X_test, y_train, y_test = train_test_split(X_res, y_res, test_size=0.2, random_state=42)
        model = XGBClassifier(
            n_estimators=100, max_depth=4, min_child_weight=6, learning_rate=0.05,
            subsample=0.8, colsample_bytree=0.8, reg_alpha=2.0, reg_lambda=1.0,
            use_label_encoder=False, eval_metric='logloss', random_state=42,
        )
        model.fit(X_train, y_train)

        y_pred = model.predict(X_test)
        print(f"\nModel accuracy: {accuracy_score(y_test, y_pred):.2f}")
        
        importances = pd.Series(model.feature_importances_, index=feature_columns).sort_values(ascending=False)
        print("\nFeature Importances:")
        print(importances.head())
        return model, scaler

    def assign_win_probabilities(self, model, scaler, features, data, ascending=False):
        features_scaled = scaler.transform(features)
        probabilities = model.predict_proba(features_scaled)[:, 1]
        data['WinProbability'] = probabilities * 100

        data.rename(columns={'DriverId': 'Driver', 'ConstructorId': 'ConstructorName'}, inplace=True)
        data.sort_values('WinProbability', ascending=ascending, inplace=True)
        return data[['Driver', 'ConstructorName', 'WinProbability']]

    def predict_race_winner(self, grand_prix_name, race_year, ascending=False):
        circuit_id = self.get_circuit_id(grand_prix_name, race_year)
        if not circuit_id:
            print(f"Could not find circuit ID for {grand_prix_name}")
            return None

        historical_data = self.prepare_historical_data()
        if historical_data is None or historical_data.empty:
            print("Prediction failed due to lack of historical data.")
            return None
        
        circuit_stats = self.calculate_circuit_stats(circuit_id, historical_data)
        features, data, historical_features, feature_columns = self.prepare_features(
            historical_data, circuit_stats, grand_prix_name, race_year
        )
        
        if data.empty:
            print(f"Not enough data to make a prediction for {grand_prix_name} {race_year}.")
            return None
            
        print("\nQualifying Positions considered for prediction:")
        print(data[['DriverId', 'QualifyingPosition']].head())

        target = historical_data['Win']
        model, scaler = self.train_model(historical_features, target, feature_columns)
        result = self.assign_win_probabilities(model, scaler, features, data, ascending=ascending)
        return result


if __name__ == "__main__":
    predictor = F1Predictor()
    prediction_year = predictor.current_year - 1
    
    schedule = predictor.get_schedule(prediction_year)
    if schedule is not None and not schedule.empty:
        grand_prix = schedule.iloc[-1]['EventName'].replace('Grand Prix', '').strip()
    
        driver_probabilities = predictor.predict_race_winner(grand_prix, prediction_year, ascending=False)
    
        if driver_probabilities is not None:
            print(f"\nPredicted probabilities for the {grand_prix} Grand Prix {prediction_year}:")
            driver_probabilities['WinProbability'] = driver_probabilities['WinProbability'].map('{:,.2f}%'.format)
            print(driver_probabilities.to_string(index=False))
        else:
            print("\nPrediction could not be made.")
    else:
        print(f"\nCould not retrieve schedule for {prediction_year} to run example.")
