import requests
import pandas as pd
import numpy as np
import fastf1
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from xgboost import XGBClassifier
from imblearn.over_sampling import SMOTE
from sklearn.preprocessing import RobustScaler

class F1Predictor:
    def __init__(self):
        """
        Initializes the F1Predictor class.
        """
        fastf1.Cache.enable_cache('cache')  # Use 'cache' directory for caching
        self.base_url = "http://ergast.com/api/f1"
        self.current_year = datetime.now().year

        self.grand_prix_data = {
            # Grand Prix data with actual dates
            "Bahrain": {"city": "Sakhir", "country": "BH", "date": "2023-03-05"},
            "Saudi Arabia": {"city": "Jeddah", "country": "SA", "date": "2023-03-19"},
            "Australia": {"city": "Melbourne", "country": "AU", "date": "2023-04-02"},
            "Azerbaijan": {"city": "Baku", "country": "AZ", "date": "2023-04-30"},
            "Miami": {"city": "Miami", "country": "US", "date": "2023-05-07"},
            "Monaco": {"city": "Monaco", "country": "MC", "date": "2023-05-28"},
            "Spain": {"city": "Barcelona", "country": "ES", "date": "2023-06-04"},
            "Canada": {"city": "Montreal", "country": "CA", "date": "2023-06-18"},
            "Austria": {"city": "Spielberg", "country": "AT", "date": "2023-07-02"},
            "Great Britain": {"city": "Silverstone", "country": "GB", "date": "2023-07-09"},
            "Hungary": {"city": "Budapest", "country": "HU", "date": "2023-07-23"},
            "Belgium": {"city": "Spa-Francorchamps", "country": "BE", "date": "2023-07-30"},
            "Netherlands": {"city": "Zandvoort", "country": "NL", "date": "2023-08-27"},
            "Italy": {"city": "Monza", "country": "IT", "date": "2023-09-03"},
            "Singapore": {"city": "Singapore", "country": "SG", "date": "2023-09-17"},
            "Japan": {"city": "Suzuka", "country": "JP", "date": "2023-09-24"},
            "Qatar": {"city": "Lusail", "country": "QA", "date": "2023-10-08"},
            "United States": {"city": "Austin", "country": "US", "date": "2023-10-22"},
            "Mexico": {"city": "Mexico City", "country": "MX", "date": "2023-10-29"},
            "Brazil": {"city": "Sao Paulo", "country": "BR", "date": "2023-11-05"},
            "Las Vegas": {"city": "Las Vegas", "country": "US", "date": "2023-11-18"},
            "Abu Dhabi": {"city": "Abu Dhabi", "country": "AE", "date": "2023-11-26"},
        }
        self.active_drivers = self.get_active_drivers()
        self.driver_standings = self.get_driver_standings()
        self.constructor_standings = self.get_constructor_standings()
        self.recent_race_results = self.get_recent_race_results(num_races=5)

    def get_active_drivers(self):
        """
        Retrieves the list of active drivers for the current season, including driver numbers and codes.
        """
        url = f"{self.base_url}/{self.current_year}/drivers.json?limit=100"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            drivers = data['MRData']['DriverTable']['Drivers']
            driver_list = []
            for driver in drivers:
                driver_number = driver.get('permanentNumber')
                if driver_number is not None:
                    driver_number = int(driver_number)
                else:
                    driver_number = None
                driver_code = driver.get('code')  # Get the driver's code (abbreviation)
                driver_list.append({
                    'DriverId': driver['driverId'],
                    'Driver': f"{driver['givenName']} {driver['familyName']}",
                    'PermanentNumber': driver_number,
                    'Abbreviation': driver_code  # Add the code to the DataFrame
                })
            return pd.DataFrame(driver_list)
        else:
            print(f"Error fetching active drivers: {response.status_code}")
            return pd.DataFrame()

    def get_driver_standings(self):
        """
        Retrieves current driver standings.
        """
        url = f"{self.base_url}/{self.current_year}/driverStandings.json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            standings = data['MRData']['StandingsTable']['StandingsLists']
            standings_list = []
            if standings:
                standings = standings[0]['DriverStandings']
                for entry in standings:
                    driver = entry['Driver']
                    constructor = entry['Constructors'][0]
                    standings_list.append({
                        'DriverId': driver['driverId'],
                        'Driver': f"{driver['givenName']} {driver['familyName']}",
                        'ConstructorId': constructor['constructorId'],
                        'Points': float(entry['points']),
                        'Wins': int(entry['wins']),
                    })
            return pd.DataFrame(standings_list)
        else:
            print(f"Error fetching driver standings: {response.status_code}")
            return pd.DataFrame()

    def get_constructor_standings(self):
        """
        Retrieves current constructor standings.
        """
        url = f"{self.base_url}/{self.current_year}/constructorStandings.json"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            standings = data['MRData']['StandingsTable']['StandingsLists']
            standings_list = []
            if standings:
                standings = standings[0]['ConstructorStandings']
                for entry in standings:
                    constructor = entry['Constructor']
                    standings_list.append({
                        'ConstructorId': constructor['constructorId'],
                        'ConstructorName': constructor['name'],
                        'ConstructorPoints': float(entry['points']),
                        'ConstructorWins': int(entry['wins']),
                    })
            return pd.DataFrame(standings_list)
        else:
            print(f"Error fetching constructor standings: {response.status_code}")
            return pd.DataFrame()

    def get_historical_race_results(self, circuit_id=None):
        """
        Retrieves historical race results for the past 5 years.
        """
        results = []
        # Collect data from the last 3 seasons
        for year in range(self.current_year - 5, self.current_year + 1):
            # Fetch all races in the season
            season_url = f"{self.base_url}/{year}.json"
            response = requests.get(season_url)
            if response.status_code == 200:
                data = response.json()
                races = data['MRData']['RaceTable']['Races']
                for race in races:
                    round_number = race['round']
                    # Skip if circuit_id is specified and doesn't match
                    if circuit_id and race['Circuit']['circuitId'] != circuit_id:
                        continue
                    # Fetch results for each race
                    url = f"{self.base_url}/{year}/{round_number}/results.json?limit=1000"
                    response = requests.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        if data['MRData']['RaceTable']['Races']:
                            race_results = data['MRData']['RaceTable']['Races'][0]
                            for result in race_results['Results']:
                                driver = result['Driver']
                                constructor = result['Constructor']
                                results.append({
                                    'Year': int(year),
                                    'RaceName': race_results['raceName'],
                                    'CircuitId': race_results['Circuit']['circuitId'],
                                    'RaceDate': datetime.strptime(race_results['date'], '%Y-%m-%d'),
                                    'DriverId': driver['driverId'],
                                    'Driver': f"{driver['givenName']} {driver['familyName']}",
                                    'ConstructorId': constructor['constructorId'],
                                    'GridPosition': int(result['grid']) if result['grid'].isdigit() else None,
                                    'FinishPosition': int(result['position']) if result['position'].isdigit() else None,
                                    'Status': result['status'],
                                    'Points': float(result['points']),
                                })
                        else:
                            print(f"No race results found for round {round_number} in {year}.")
                    else:
                        print(f"Error fetching results for round {round_number} in {year}: {response.status_code}")
            else:
                print(f"Error fetching race schedule for {year}: {response.status_code}")
        return pd.DataFrame(results)

    def get_circuit_id(self, track_name):
        circuit_mapping = {
            "bahrain": "bahrain",
            "saudi arabia": "jeddah",
            "australia": "albert_park",
            "azerbaijan": "baku",
            "miami": "miami",
            "monaco": "monaco",
            "spain": "catalunya",
            "canada": "villeneuve",
            "austria": "red_bull_ring",
            "great britain": "silverstone",
            "britain": "silverstone",
            "hungary": "hungaroring",
            "belgium": "spa",
            "netherlands": "zandvoort",
            "italy": "monza",
            "singapore": "marina_bay",
            "japan": "suzuka",
            "qatar": "losail",
            "united states": "cota",
            "mexico": "rodriguez",
            "brazil": "interlagos",
            "las vegas": "las_vegas",
            "abu dhabi": "yas_marina",
        }
        return circuit_mapping.get(track_name.lower(), track_name.lower())

    def get_recent_performance(self):
        """
        Retrieves recent performance of drivers for the current season.
        """
        standings = self.driver_standings
        if not standings.empty:
            return standings.rename(columns={'Points': 'Points', 'Wins': 'Wins'})
        else:
            return pd.DataFrame()

    def get_recent_race_results(self, num_races=5):
        """
        Retrieves results from the last few completed races.
        """
        results = []
        # Fetch the race schedule for the current season
        schedule_url = f"{self.base_url}/{self.current_year}.json"
        response = requests.get(schedule_url)
        if response.status_code == 200:
            data = response.json()
            races = data['MRData']['RaceTable']['Races']
            # Filter races that have already occurred
            today = datetime.now()
            completed_races = []
            for race in races:
                race_date = datetime.strptime(race['date'], '%Y-%m-%d')
                if race_date < today:
                    completed_races.append(race)
            # Get the last num_races races
            recent_races = completed_races[-num_races:]
            if not recent_races:
                print("No completed races found for the current year.")
                return pd.DataFrame()
            for race in recent_races:
                round_number = race['round']
                url = f"{self.base_url}/{self.current_year}/{round_number}/results.json?limit=1000"
                response = requests.get(url)
                if response.status_code == 200:
                    data = response.json()
                    if data['MRData']['RaceTable']['Races']:
                        race_results = data['MRData']['RaceTable']['Races'][0]
                        for result in race_results['Results']:
                            driver = result['Driver']
                            constructor = result['Constructor']
                            results.append({
                                'RaceName': race_results['raceName'],
                                'DriverId': driver['driverId'],
                                'ConstructorId': constructor['constructorId'],
                                'Points': float(result['points']),
                                'FinishPosition': int(result['position']) if result['position'].isdigit() else None,
                            })
                    else:
                        print(f"No race results found for round {round_number} of {self.current_year}.")
                else:
                    print(f"Error fetching results for round {round_number}: {response.status_code}")
        else:
            print(f"Error fetching race schedule: {response.status_code}")
        return pd.DataFrame(results)

    def get_round_number(self, grand_prix_name, year):
        """
        Retrieves the round number for a specific Grand Prix in a given year.
        """
        schedule_url = f"{self.base_url}/{year}.json"
        response = requests.get(schedule_url)
        if response.status_code == 200:
            data = response.json()
            races = data['MRData']['RaceTable']['Races']
            for race in races:
                if race['raceName'].lower() == grand_prix_name.lower() + " grand prix" or race['raceName'].lower() == grand_prix_name.lower():
                    return race['round']
            print(f"Race {grand_prix_name} not found in {year} schedule.")
            return None
        else:
            print(f"Error fetching race schedule: {response.status_code}")
            return None

    def get_qualifying_results(self, grand_prix_name, year):
        """
        Retrieves qualifying results or simulates them using practice session data when qualifying results are not available.
        """
        # Enable cache
        fastf1.Cache.enable_cache('cache')

        # Get event details
        try:
            event = fastf1.get_event(year, grand_prix_name)
        except Exception as e:
            print(f"Error fetching event data for {grand_prix_name} {year}: {e}")
            return pd.DataFrame()

        # Define the sessions to try in order
        session_types = ['Q', 'SQ', 'SS', 'FP3', 'FP2', 'FP1']
        session_loaded = False

        for session_type in session_types:
            try:
                session = fastf1.get_session(year, grand_prix_name, session_type)
                session.load()

                # Check if session has results
                if session.results is None or session.results.empty:
                    print(f"No session results available for {grand_prix_name} {year} in session '{session_type}'. Trying next session type.")
                    continue  # Try the next session type
                else:
                    session_loaded = True
                    break  # Exit the loop if a session loads and has results
            except Exception as e:
                print(f"Error loading session '{session_type}' for {grand_prix_name} {year}: {e}")
                continue  # Try the next session type

        if not session_loaded:
            print(f"No qualifying or practice data available for {grand_prix_name} {year}.")
            return pd.DataFrame()

        # Proceed to get the session results
        if session_type in ['FP1', 'FP2', 'FP3']:
            # Get all laps
            laps = session.laps

            # Remove laps with invalid lap times
            laps = laps.dropna(subset=['LapTime'])

            # Get the fastest lap for each driver
            fastest_laps = laps.groupby('Driver').apply(lambda x: x.nsmallest(1, 'LapTime')).reset_index(drop=True)

            # Select needed columns
            lap_times = fastest_laps[['Driver', 'LapTime']]

            # Sort drivers by their fastest lap times
            lap_times = lap_times.sort_values(by='LapTime').reset_index(drop=True)

            # Assign positions
            lap_times['Position'] = lap_times.index + 1

            # Map drivers to DriverId using 'Abbreviation'
            if self.active_drivers.empty:
                self.active_drivers = self.get_active_drivers()
            
            # Map 'Driver' to 'Abbreviation' in session.results
            driver_map = session.results[['DriverNumber', 'Abbreviation', 'FullName']].drop_duplicates()
            lap_times = lap_times.merge(driver_map, left_on='Driver', right_on='Abbreviation', how='left')

            # Map Abbreviation to DriverId
            abbr_to_driverid = self.active_drivers.set_index('Abbreviation')['DriverId'].to_dict()
            lap_times['DriverId'] = lap_times['Abbreviation'].map(abbr_to_driverid)

            # Prepare qualifying_results DataFrame
            qualifying_results = lap_times[['DriverId', 'Abbreviation', 'Position']].copy()
            qualifying_results.rename(columns={'Position': 'QualifyingPosition'}, inplace=True)
        else:
            # Use qualifying results as is
            results = session.results

            # Map drivers using abbreviations
            if 'Abbreviation' in results.columns:
                if self.active_drivers.empty:
                    self.active_drivers = self.get_active_drivers()
                # Ensure 'Abbreviation' is available in active_drivers
                if 'Abbreviation' in self.active_drivers.columns:
                    # Map Abbreviation to DriverId
                    abbr_to_driverid = self.active_drivers.set_index('Abbreviation')['DriverId'].to_dict()
                    results['DriverId'] = results['Abbreviation'].map(abbr_to_driverid)
                else:
                    print("'Abbreviation' column not found in active_drivers.")
                    return pd.DataFrame()
            else:
                print("'Abbreviation' column not found in session results.")
                return pd.DataFrame()

            # Drop entries without DriverId mapping or missing Position
            qualifying_results = results.dropna(subset=['DriverId', 'Position'])
            qualifying_results = qualifying_results[['DriverId', 'Abbreviation', 'Position']].copy()
            qualifying_results.rename(columns={'Position': 'QualifyingPosition'}, inplace=True)

        # Drop entries without DriverId mapping
        qualifying_results = qualifying_results.dropna(subset=['DriverId'])

        # Convert 'QualifyingPosition' to int
        qualifying_results['QualifyingPosition'] = qualifying_results['QualifyingPosition'].astype(int)

        return qualifying_results

    def get_circuit_features(self, circuit_id):
        """
        Returns circuit-specific features.
        """
        circuit_features = {
            'bahrain': {'CircuitType': 'Permanent', 'CircuitLength': 5.412},
            'jeddah': {'CircuitType': 'Street', 'CircuitLength': 6.174},
            'albert_park': {'CircuitType': 'Street', 'CircuitLength': 5.278},
            'baku': {'CircuitType': 'Street', 'CircuitLength': 6.003},
            'miami': {'CircuitType': 'Street', 'CircuitLength': 5.412},
            'monaco': {'CircuitType': 'Street', 'CircuitLength': 3.337},
            'catalunya': {'CircuitType': 'Permanent', 'CircuitLength': 4.655},
            'villeneuve': {'CircuitType': 'Street', 'CircuitLength': 4.361},
            'red_bull_ring': {'CircuitType': 'Permanent', 'CircuitLength': 4.318},
            'silverstone': {'CircuitType': 'Permanent', 'CircuitLength': 5.891},
            'hungaroring': {'CircuitType': 'Permanent', 'CircuitLength': 4.381},
            'spa': {'CircuitType': 'Permanent', 'CircuitLength': 7.004},
            'zandvoort': {'CircuitType': 'Permanent', 'CircuitLength': 4.259},
            'monza': {'CircuitType': 'Permanent', 'CircuitLength': 5.793},
            'marina_bay': {'CircuitType': 'Street', 'CircuitLength': 5.063},
            'suzuka': {'CircuitType': 'Permanent', 'CircuitLength': 5.807},
            'losail': {'CircuitType': 'Permanent', 'CircuitLength': 5.380},
            'cota': {'CircuitType': 'Permanent', 'CircuitLength': 5.513},
            'rodriguez': {'CircuitType': 'Permanent', 'CircuitLength': 4.304},
            'interlagos': {'CircuitType': 'Permanent', 'CircuitLength': 4.309},
            'las_vegas': {'CircuitType': 'Street', 'CircuitLength': 6.120},
            'yas_marina': {'CircuitType': 'Permanent', 'CircuitLength': 5.554},
        }
        return circuit_features.get(circuit_id, {'CircuitType': 'Unknown', 'CircuitLength': 5.0})

    def get_drivers_in_race(self, grand_prix_name, year):
        """
        Retrieves the list of drivers participating in a specific race.
        """
        round_number = self.get_round_number(grand_prix_name, year)
        if not round_number:
            return []

        url = f"{self.base_url}/{year}/{round_number}/drivers.json?limit=100"
        response = requests.get(url)
        if response.status_code == 200:
            data = response.json()
            drivers = data['MRData']['DriverTable']['Drivers']
            driver_list = [driver['driverId'] for driver in drivers]
            return driver_list
        else:
            print(f"Error fetching drivers for {grand_prix_name} {year}: {response.status_code}")
            return []

    def get_historical_qualifying_results(self):
        """
        Retrieves historical qualifying results for the past 3 years.
        """
        qualifying_results = []
        # Collect data from the last 3 seasons
        for year in range(self.current_year - 3, self.current_year):
            # Fetch all races in the season
            season_url = f"{self.base_url}/{year}.json"
            response = requests.get(season_url)
            if response.status_code == 200:
                data = response.json()
                races = data['MRData']['RaceTable']['Races']
                for race in races:
                    round_number = race['round']
                    race_date_str = race['date']
                    race_date = pd.to_datetime(race_date_str)
                    # Fetch qualifying results for each race
                    url = f"{self.base_url}/{year}/{round_number}/qualifying.json?limit=1000"
                    response = requests.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        if data['MRData']['RaceTable']['Races']:
                            race_qualifying = data['MRData']['RaceTable']['Races'][0]
                            if 'QualifyingResults' in race_qualifying:
                                for result in race_qualifying['QualifyingResults']:
                                    driver = result['Driver']
                                    qualifying_results.append({
                                        'RaceDate': race_date,
                                        'DriverId': driver['driverId'],
                                        'QualifyingPosition': int(result['position'])
                                    })
                            else:
                                print(f"No qualifying results found for round {round_number} in {year}.")
                        else:
                            print(f"No qualifying data found for round {round_number} in {year}.")
                    else:
                        print(f"Error fetching qualifying results for round {round_number} in {year}: {response.status_code}")
            else:
                print(f"Error fetching race schedule for {year}: {response.status_code}")
        return pd.DataFrame(qualifying_results)

    def prepare_historical_data(self):
        """
        Prepares historical data by computing cumulative and recent performance metrics.
        """
        # Get historical race results
        historical_results = self.get_historical_race_results()

        if historical_results.empty:
            print("No historical data available")
            return None

        # Ensure 'RaceDate' is of datetime type
        historical_results['RaceDate'] = pd.to_datetime(historical_results['RaceDate'])

        # Create 'Win' column
        historical_results['Win'] = (historical_results['FinishPosition'] == 1).astype(int)

        # Compute cumulative points and wins for drivers up to each race
        historical_results.sort_values(['DriverId', 'RaceDate'], inplace=True)
        historical_results['CumulativePoints'] = historical_results.groupby('DriverId')['Points'].cumsum() - historical_results['Points']
        historical_results['CumulativeWins'] = historical_results.groupby('DriverId')['Win'].cumsum() - historical_results['Win']

        # Compute cumulative points and wins for constructors up to each race
        historical_results['ConstructorWin'] = (historical_results['FinishPosition'] == 1).astype(int)
        historical_results['ConstructorCumulativePoints'] = historical_results.groupby('ConstructorId')['Points'].cumsum() - historical_results['Points']
        historical_results['ConstructorCumulativeWins'] = historical_results.groupby('ConstructorId')['ConstructorWin'].cumsum() - historical_results['ConstructorWin']

        # Calculate recent performance (last 5 races) without data leakage
        historical_results['AvgPointsLast5'] = historical_results.groupby('DriverId')['Points'] \
            .rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True).fillna(0)
        historical_results['AvgFinishPositionLast5'] = historical_results.groupby('DriverId')['FinishPosition'] \
            .rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True).fillna(0)
        historical_results['WinsLast5'] = historical_results.groupby('DriverId')['Win'] \
            .rolling(window=5, min_periods=1).sum().shift(1).reset_index(level=0, drop=True).fillna(0)

        # Filter active drivers
        active_driver_ids = self.active_drivers['DriverId'].unique()
        historical_results = historical_results[historical_results['DriverId'].isin(active_driver_ids)]

        return historical_results

    def calculate_circuit_stats(self, circuit_id, historical_data):
        """
        Calculates circuit-specific statistics.
        """
        # Driver's performance at the specific circuit
        circuit_results = self.get_historical_race_results(circuit_id=circuit_id)
        if circuit_results.empty:
            # If no data for circuit, use overall performance
            circuit_results = historical_data.copy()

        # Ensure 'Win' column exists in circuit_results
        if 'Win' not in circuit_results.columns:
            circuit_results['Win'] = (circuit_results['FinishPosition'] == 1).astype(int)

        # Calculate circuit-specific stats
        circuit_stats = circuit_results.groupby('DriverId').agg(
            AvgFinishPositionCircuit=('FinishPosition', 'mean'),
            BestFinishPositionCircuit=('FinishPosition', 'min'),
            TotalPointsCircuit=('Points', 'sum'),
            WinsCircuit=('Win', 'sum'),
            RacesAtCircuit=('RaceDate', 'count')
        ).reset_index()
        # Calculate WinRateCircuit
        circuit_stats['WinRateCircuit'] = circuit_stats['WinsCircuit'] / circuit_stats['RacesAtCircuit']

        return circuit_stats

    def prepare_features(self, historical_data, circuit_stats, grand_prix_name, race_year):
        """
        Prepares the feature set for modeling.
        """
        # Get qualifying results
        qualifying_results = self.get_qualifying_results(grand_prix_name, race_year)

        # Determine participating drivers
        if not qualifying_results.empty:
            # Use drivers from qualifying results as participating drivers
            drivers_in_race = qualifying_results['DriverId'].unique()
        else:
            # If qualifying data is not available, use get_drivers_in_race to get drivers in the race
            drivers_in_race = self.get_drivers_in_race(grand_prix_name, race_year)
            if not drivers_in_race:
                print(f"No entry list available for {grand_prix_name} {race_year}. Proceeding with all active drivers.")
                drivers_in_race = self.active_drivers['DriverId'].unique()

        # Filter driver standings to include only participating drivers
        data = self.driver_standings[self.driver_standings['DriverId'].isin(drivers_in_race)].copy()

        # Merge with constructor standings
        data = data.merge(
            self.constructor_standings[['ConstructorId', 'ConstructorName', 'ConstructorPoints', 'ConstructorWins']],
            on='ConstructorId', how='left'
        )

        # Merge with circuit stats
        data = data.merge(
            circuit_stats[['DriverId', 'AvgFinishPositionCircuit', 'BestFinishPositionCircuit',
                        'TotalPointsCircuit', 'WinsCircuit', 'WinRateCircuit']],
            on='DriverId', how='left'
        )

        # Add qualifying positions
        if not qualifying_results.empty:
            data = data.merge(qualifying_results[['DriverId', 'QualifyingPosition']], on='DriverId', how='left')
        else:
            # Use average grid positions if qualifying data not available
            avg_grid_positions = historical_data.groupby('DriverId')['GridPosition'].mean().reset_index()
            avg_grid_positions.rename(columns={'GridPosition': 'QualifyingPosition'}, inplace=True)
            data = data.merge(avg_grid_positions, on='DriverId', how='left')

        # Remove drivers with invalid qualifying positions (e.g., zero or missing)
        data = data[data['QualifyingPosition'].notnull()]
        data = data[data['QualifyingPosition'] > 0]

        # For historical data, include qualifying positions
        historical_qualifying = self.get_historical_qualifying_results()

        # Ensure 'RaceDate' is datetime in both DataFrames
        historical_data['RaceDate'] = pd.to_datetime(historical_data['RaceDate'])
        if not historical_qualifying.empty:
            historical_qualifying['RaceDate'] = pd.to_datetime(historical_qualifying['RaceDate'])

            historical_data = historical_data.merge(
                historical_qualifying[['RaceDate', 'DriverId', 'QualifyingPosition']],
                on=['RaceDate', 'DriverId'], how='left'
            )
            # Fill missing QualifyingPosition values with GridPosition
            historical_data['QualifyingPosition'] = historical_data['QualifyingPosition'] \
                .fillna(historical_data['GridPosition'])
        else:
            # Use 'GridPosition' as 'QualifyingPosition' if qualifying data not available
            historical_data['QualifyingPosition'] = historical_data['GridPosition']

        # Fill any remaining missing QualifyingPosition values with the mean
        historical_data['QualifyingPosition'] = historical_data['QualifyingPosition'] \
            .fillna(historical_data['QualifyingPosition'].mean())

        # Calculate average qualifying position over recent 5 races
        historical_data['AvgQualifyingPositionLast5'] = historical_data.groupby('DriverId')['QualifyingPosition'] \
            .rolling(window=5, min_periods=1).mean().shift(1).reset_index(level=0, drop=True)
        # Fill missing values with overall average qualifying position
        overall_avg_qual_pos = historical_data['QualifyingPosition'].mean()
        historical_data['AvgQualifyingPositionLast5'] = historical_data['AvgQualifyingPositionLast5'] \
            .fillna(overall_avg_qual_pos)

        # Add recent performance metrics to 'data'
        # Get the most recent race date in historical_data
        most_recent_date = historical_data['RaceDate'].max()
        recent_performance = historical_data[historical_data['RaceDate'] == most_recent_date][
            ['DriverId', 'AvgPointsLast5', 'AvgFinishPositionLast5', 'WinsLast5', 'AvgQualifyingPositionLast5']]
        data = data.merge(recent_performance, on='DriverId', how='left')

        # Fill missing values in recent performance metrics
        recent_perf_cols = ['AvgPointsLast5', 'AvgFinishPositionLast5', 'WinsLast5', 'AvgQualifyingPositionLast5']
        for col in recent_perf_cols:
            data[col] = data[col].fillna(data[col].mean())

        # Add 'QualifyingAvailable' feature
        data['QualifyingAvailable'] = data['QualifyingPosition'].notnull().astype(int)
        historical_data['QualifyingAvailable'] = historical_data['QualifyingPosition'].notnull().astype(int)

        # Remove drivers with invalid qualifying positions (e.g., zero or missing)
        data = data[data['QualifyingPosition'].notnull()]
        data = data[data['QualifyingPosition'] > 0]

        # Add circuit features
        circuit_features = self.get_circuit_features(self.get_circuit_id(grand_prix_name))
        data['CircuitType'] = circuit_features['CircuitType']
        data['CircuitLength'] = circuit_features['CircuitLength']

        # Convert categorical features to numerical
        data['CircuitType'] = data['CircuitType'].map({'Permanent': 0, 'Street': 1, 'Unknown': 2})

        # Fill missing values
        data.fillna(0, inplace=True)

        # Prepare feature columns list
        feature_columns = [
            'QualifyingPosition',
            'Wins',
            'Points',
            'ConstructorPoints',
            'ConstructorWins',
            'AvgFinishPositionCircuit',
            'BestFinishPositionCircuit',
            'TotalPointsCircuit',
            'WinsCircuit',
            'WinRateCircuit',
            'AvgPointsLast5',
            'AvgFinishPositionLast5',
            'WinsLast5',
            'AvgQualifyingPositionLast5',
            'QualifyingAvailable',
            'CircuitType',
            'CircuitLength',
        ]

        features = data[feature_columns]

        # Add circuit features to 'historical_data'
        historical_data['CircuitType'] = historical_data['CircuitId'].map(
            lambda x: self.get_circuit_features(x)['CircuitType']).map({'Permanent': 0, 'Street': 1, 'Unknown': 2})
        historical_data['CircuitLength'] = historical_data['CircuitId'].map(
            lambda x: self.get_circuit_features(x)['CircuitLength'])

        # Prepare historical data
        historical_data['Points'] = historical_data['CumulativePoints']
        historical_data['Wins'] = historical_data['CumulativeWins']
        historical_data['ConstructorPoints'] = historical_data['ConstructorCumulativePoints']
        historical_data['ConstructorWins'] = historical_data['ConstructorCumulativeWins']

        # Merge circuit_stats to historical_data
        historical_data = historical_data.merge(
            circuit_stats[['DriverId', 'AvgFinishPositionCircuit', 'BestFinishPositionCircuit',
                        'TotalPointsCircuit', 'WinsCircuit', 'WinRateCircuit']],
            on='DriverId', how='left'
        )

        # Fill missing values in recent performance metrics
        historical_perf_cols = ['AvgPointsLast5', 'AvgFinishPositionLast5', 'WinsLast5', 'AvgQualifyingPositionLast5']
        for col in historical_perf_cols:
            historical_data[col] = historical_data[col].fillna(historical_data[col].mean())

        # Prepare features for historical data
        historical_features = historical_data[feature_columns].fillna(0)

        return features, data, historical_features, feature_columns

    def train_model(self, historical_features, target, feature_columns):
        """
        Trains the predictive model using historical data.
        """
        # Handle missing values and infinite values
        historical_features = historical_features.replace([np.inf, -np.inf], np.nan).fillna(0)

        # Apply log transformation to 'WinRateCircuit' to reduce skewness
        historical_features['WinRateCircuit'] = np.log1p(historical_features['WinRateCircuit'])

        # Scale features using RobustScaler
        scaler = RobustScaler()
        scaler.fit(historical_features)

        # Scale training features
        historical_features_scaled = scaler.transform(historical_features)

        # Handle class imbalance
        sm = SMOTE(random_state=42)
        X_res, y_res = sm.fit_resample(historical_features_scaled, target)

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X_res, y_res, test_size=0.2, random_state=42
        )

        # Adjust model parameters
        model = XGBClassifier(
            n_estimators=100,
            max_depth=4,
            min_child_weight=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_alpha=2.0,
            reg_lambda=1.0,
            use_label_encoder=False,
            eval_metric='logloss',
            random_state=42,
        )

        model.fit(X_train, y_train)

        # Evaluate model
        y_pred = model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        print(f"Model accuracy: {accuracy:.2f}")
        print("Classification Report:")
        print(classification_report(y_test, y_pred))

        # Get feature importances
        importances = model.feature_importances_
        feature_importances = pd.Series(importances, index=feature_columns)
        print("Feature Importances:")
        print(feature_importances.sort_values(ascending=False))

        return model, scaler

    def assign_win_probabilities(self, model, scaler, features, data, ascending=False):
        """
        Uses the trained model to assign win probabilities to the drivers.
        """
        # Ensure 'WinRateCircuit' is transformed in prediction features
        features = features.copy()
        features['WinRateCircuit'] = np.log1p(features['WinRateCircuit'])
        
        # Apply scaling factors to prediction features
        scaling_factors = {
            'QualifyingPosition': 1.0,
            'Wins': 1.0,
            'Points': 1.0,
            'ConstructorPoints': 1.0,
            'ConstructorWins': 1.0,
            'AvgFinishPositionCircuit': 3.0,
            'BestFinishPositionCircuit': 3.0,
            'TotalPointsCircuit': 3.0,
            'WinsCircuit': 3.0,
            'WinRateCircuit': 3.0,
            'AvgPointsLast5': 3.0,
            'AvgFinishPositionLast5': 3.0,
            'WinsLast5': 3.0,
            'AvgQualifyingPositionLast5': 1.0,
            'QualifyingAvailable': 1.0,
            'CircuitType': 1.0,
            'CircuitLength': 1.0,
        }
        
        for feature, factor in scaling_factors.items():
            if feature in features.columns:
                features[feature] *= factor
        
        # Handle missing values and infinite values
        features = features.replace([np.inf, -np.inf], np.nan).fillna(0)
        
        # Scale prediction features
        features_scaled = scaler.transform(features)
        
        # Get predicted probabilities for prediction data
        probabilities = model.predict_proba(features_scaled)[:, 1]
        
        # Assign probabilities to drivers
        data['WinProbability'] = probabilities * 100  # Convert to percentage

        if 'DriverId' in data.columns:
            participating_drivers = set(data['DriverId'])
            all_active_drivers = set(self.active_drivers['DriverId'])
            non_participating_drivers = all_active_drivers - participating_drivers
            # Add non-participating drivers to the data with WinProbability zero
            non_participating_data = self.active_drivers[self.active_drivers['DriverId'].isin(non_participating_drivers)]
            non_participating_data = non_participating_data.merge(
                self.driver_standings[['DriverId', 'ConstructorId']], on='DriverId', how='left'
            )
            non_participating_data = non_participating_data.merge(
                self.constructor_standings[['ConstructorId', 'ConstructorName']], on='ConstructorId', how='left'
            )
            non_participating_data['WinProbability'] = 0.0
            # Combine data
            data = pd.concat([data, non_participating_data[['Driver', 'ConstructorName', 'WinProbability']]], ignore_index=True)
    
        # Remove any duplicate entries for drivers
        data = data.drop_duplicates(subset=['DriverId'], keep='first')
    
        # Sort drivers by ascending or descending win probability
        data.sort_values('WinProbability', ascending=ascending, inplace=True)
        
        # Return the DataFrame containing drivers and their win probabilities
        return data[['Driver', 'ConstructorName', 'WinProbability']]

    def predict_race_winner(self, grand_prix_name, race_year, ascending=False):
        """
        Predicts the winner of a specified Grand Prix.
        """
        circuit_id = self.get_circuit_id(grand_prix_name)

        # Get race details
        race_info = self.grand_prix_data.get(grand_prix_name)
        if not race_info:
            print(f"No data available for {grand_prix_name}")
            return None

        # Prepare historical data
        historical_data = self.prepare_historical_data()

        # Calculate circuit-specific stats
        circuit_stats = self.calculate_circuit_stats(circuit_id, historical_data)

        # Prepare features for modeling
        features, data, historical_features, feature_columns = self.prepare_features(
            historical_data,
            circuit_stats,
            grand_prix_name,
            race_year,
        )

        print("Qualifying Positions:")
        print(data[['Driver', 'ConstructorName', 'QualifyingPosition']])

        # Target variable
        target = historical_data['Win']

        # Train the model
        model, scaler = self.train_model(historical_features, target, feature_columns)

        # Assign win probabilities
        result = self.assign_win_probabilities(model, scaler, features, data, ascending=ascending)

        return result

# Example usage
if __name__ == "__main__":
    predictor = F1Predictor()
    grand_prix = 'Abu Dhabi'  # Grand Prix name
    race_year = 2024        # Year of the race

    driver_probabilities = predictor.predict_race_winner(grand_prix, race_year, ascending=False)
    if driver_probabilities is not None:
        print(f"Predicted probabilities for the {grand_prix} Grand Prix {race_year}:")
        print(driver_probabilities.to_string(index=False))
    else:
        print("Prediction could not be made due to insufficient data.")
