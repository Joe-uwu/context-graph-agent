import requests
import pandas as pd
import numpy as np
import fastf1
from datetime import datetime, timedelta
from sklearn.model_selection import train_test_split, GridSearchCV, cross_val_score
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import mean_squared_error, mean_absolute_error, r2_score

class F1Predictor:
    def __init__(self):
        """
        Initializes the F1Predictor class.
        Enables caching for fastf1 data and sets base configurations such as the API base URL,
        the current year, and predefined grand prix data.
        """
        fastf1.Cache.enable_cache('__pycache__')
        self.base_url = "http://ergast.com/api/f1"
        self.current_year = datetime.now().year
        self.api_key = "c5d27272ec454d7b9f6234316241009"
        self.grand_prix_data = {
        "Bahrain": {"city": "Sakhir", "country": "BH", "date": "2024-02-29"},
        "Saudi Arabia": {"city": "Jeddah", "country": "SA", "date": "2024-03-07"},
        "Australia": {"city": "Melbourne", "country": "AU", "date": "2024-03-21"},
        "Japan": {"city": "Suzuka", "country": "JP", "date": "2024-04-04"},
        "China": {"city": "Shanghai", "country": "CN", "date": "2024-04-18"},
        "Miami": {"city": "Miami", "country": "US", "date": "2024-05-03"},
        "Emilia Romagna": {"city": "Imola", "country": "IT", "date": "2024-05-16"},
        "Monaco": {"city": "Monaco", "country": "MC", "date": "2024-05-23"},
        "Canada": {"city": "Montreal", "country": "CA", "date": "2024-06-07"},
        "Spain": {"city": "Barcelona", "country": "ES", "date": "2024-06-20"},
        "Austria": {"city": "Spielberg", "country": "AT", "date": "2024-06-28"},
        "United Kingdom": {"city": "Silverstone", "country": "GB", "date": "2024-07-04"},
        "Hungary": {"city": "Budapest", "country": "HU", "date": "2024-07-18"},
        "Belgium": {"city": "Spa", "country": "BE", "date": "2024-07-25"},
        "Netherlands": {"city": "Zandvoort", "country": "NL", "date": "2024-08-22"},
        "Italy": {"city": "Monza", "country": "IT", "date": "2024-08-29"},
        "Azerbaijan": {"city": "Baku", "country": "AZ", "date": "2024-09-15"},
        "Singapore": {"city": "Singapore", "country": "SG", "date": "2024-09-22"},
        "United States": {"city": "Austin", "country": "US", "date": "2024-10-20"},
        "Mexico": {"city": "Mexico City", "country": "MX", "date": "2024-10-27"},
        "Brazil": {"city": "Sao Paulo", "country": "BR", "date": "2024-11-03"},
        "Las Vegas": {"city": "Las Vegas", "country": "US", "date": "2024-11-23"},
        "Qatar": {"city": "Lusail", "country": "QA", "date": "2024-12-1"},
        "Abu Dhabi": {"city": "Abu Dhabi", "country": "AE", "date": "2024-12-08"}
        }

    def get_winners_last_three_years(self, track_name):
        """
        Retrieves the winners from the last three years for a specified track.
        Args:
            track_name (str): The name of the track to query.

        Returns:
            pd.DataFrame: A DataFrame containing the year, driver name, and team name of the winners.
        """
                
        winners = []
        for year in range(self.current_year - 3, self.current_year):
            try:
                url = f"{self.base_url}/{year}/circuits/{self.get_circuit_id(track_name)}/results.json"
                response = requests.get(url)
                response.raise_for_status()
                data = response.json()

                race_data = data['MRData']['RaceTable']['Races']
                if race_data:
                    winner = race_data[0]['Results'][0]
                    winners.append({
                        'Year': year,
                        'Driver': f"{winner['Driver']['givenName']} {winner['Driver']['familyName']}",
                        'Team': winner['Constructor']['name']
                    })
                else:
                    print(f"No race data found for {track_name} in {year}")
            except requests.RequestException as e:
                print(f"Error retrieving data for {track_name} in {year}: {e}")
            except (KeyError, IndexError) as e:
                print(f"Error parsing data for {track_name} in {year}: {e}")

        return pd.DataFrame(winners)

    def get_circuit_id(self, track_name):
        """
        Retrieves the circuit ID based on the given track name.
        Args:
            track_name (str): The name of the track.

        Returns:
            str: The circuit ID associated with the track name.
        """
        circuit_mapping = {
            "Azerbaijan": "baku",
            "Bahrain": "bahrain",
            "Monaco": "monaco",
            "Silverstone": "silverstone",
            "Monza": "monza",
            "Australia": "albert_park",
            "Austria": "red_bull_ring",
            "Belgium": "spa",
            "Brazil": "interlagos",
            "Canada": "circuit_gilles_villeneuve",
            "France": "paul_ricard",
            "Germany": "hockenheim",
            "Hungary": "hungaroring",
            "Japan": "suzuka",
            "Mexico": "rodriguez",
            "Netherlands": "zandvoort",
            "Russia": "sochi",
            "Saudi Arabia": "jeddah",
            "Singapore": "marina_bay",
            "Spain": "catalunya",
            "USA": "cota",  
            "Vietnam": "hanoi",
            "China": "shanghai",
            "Qatar": "lusail",
            "Miami": "miami",
            "Imola": "imola",
            "Las Vegas": "las_vegas",
            "Abu Dhabi": "yas_marina"
        }
        return circuit_mapping.get(track_name, track_name.lower())

    def get_current_season_data(self, year=None):
        """
        Fetches race results data for the current or specified season.
        Args:
            year (int, optional): The year of the season to fetch. Defaults to current year.

        Returns:
            pd.DataFrame: A DataFrame containing detailed race results.
        """
                
        if year is None:
            year = datetime.now().year

        try:
            season = fastf1.get_event_schedule(year)
        except ValueError as e:
            print(f"Error: Unable to get event schedule for year {year}. {str(e)}")
            return pd.DataFrame()

        results = []

        for _, event in season.iterrows():
            if event['EventDate'] < datetime.now():
                try:
                    race = fastf1.get_session(year, event['EventName'], 'R')
                    race.load()
                    result = race.results[['DriverNumber', 'Position', 'Points']]
                    result['RoundNumber'] = event['RoundNumber']
                    result['TrackName'] = event['EventName']
                    results.append(result)
                except Exception as e:
                    print(f"Error loading data for {event['EventName']}: {e}")

        return pd.concat(results, ignore_index=True) if results else pd.DataFrame()
    

    def get_weather_forecast(self, city, country, date, api_key):
        """
        Fetches weather forecast for a specified location and date.
        Args:
            city (str): The city for the forecast.
            country (str): The country code for the forecast.
            date (datetime.date): The date for the forecast.
            api_key (str): API key for the weather service.

        Returns:
            dict: Weather conditions including temperature, description, and rain chances.
        """
                
        base_url = "http://api.weatherapi.com/v1/forecast.json"
        days_from_now = (date - datetime.now().date()).days
        if days_from_now < 0 or days_from_now > 3:
            return "Weather forecast is only available for the next 3 days"
        params = {
            "key": api_key,
            "q": f"{city},{country}",
            "days": days_from_now + 1,
            "aqi": "no",
            "alerts": "no"
        }
        response = requests.get(base_url, params=params)
        if response.status_code == 200:
            data = response.json()
            forecast_day = data['forecast']['forecastday'][days_from_now]
            return {
                "temperature": forecast_day['day']['avgtemp_c'],
                "description": forecast_day['day']['condition']['text'],
                "is_wet": forecast_day['day']['daily_will_it_rain'] == 1,
                "rain_chance": forecast_day['day']['daily_chance_of_rain']
            }
        else:
            return f"Error fetching weather data: {response.status_code}"

    def predict_track_conditions(self, weather_data):
        """
        Predicts track conditions based on the provided weather data.
        Args:
            weather_data (dict): Weather data including temperature and wet conditions.

        Returns:
            dict: Predicted track conditions including temperature, wet status, and overall condition.
        """
                
        if isinstance(weather_data, str):
            return weather_data
        temp = weather_data['temperature']
        is_wet = weather_data['is_wet']
        track_condition = "Wet" if is_wet else "Cool" if temp < 20 else "Moderate" if 20 <= temp < 30 else "Hot"
        return {
            "track_temperature": temp,
            "is_wet": is_wet,
            "track_condition": track_condition,
            "rain_chance": weather_data['rain_chance']
        }

    def get_grand_prix_forecast_for_race_day(self, grand_prix_name, api_key):
        """
        Provides weather and track condition forecasts for a specified Grand Prix on its race day.
        Args:
            grand_prix_name (str): The name of the Grand Prix.
            api_key (str): API key for accessing weather data.

        Returns:
            dict: Forecast data including Grand Prix name, race date, and track conditions.
        """
                
        if grand_prix_name not in self.grand_prix_data:
            return "Grand Prix not found in the database"
        
        location = self.grand_prix_data[grand_prix_name]
        race_date = datetime.strptime(location['date'], "%Y-%m-%d").date()
        
        days_until_race = (race_date - datetime.now().date()).days
        if days_until_race < 0 or days_until_race > 3:
            return f"Weather forecast is not available for {race_date}. It's only available for the next 3 days."
        
        weather_data = self.get_weather_forecast(location['city'], location['country'], race_date, api_key)
        track_conditions = self.predict_track_conditions(weather_data)
        
        return {
            "grand_prix": grand_prix_name,
            "race_date": race_date,
            "forecast": track_conditions
        }

    def check_upcoming_race_forecasts(self):
        """
        Checks and returns the weather and track condition forecasts for all upcoming races within the next 3 days.
        Returns:
            list: A list of forecasts for upcoming races.
        """
                
        today = datetime.now().date()
        upcoming_races = []

        for gp_name, gp_info in self.grand_prix_data.items():
            race_date = datetime.strptime(gp_info['date'], "%Y-%m-%d").date()
            days_until_race = (race_date - today).days
            if 0 <= days_until_race <= 3:
                forecast = self.get_grand_prix_forecast_for_race_day(gp_name)
                upcoming_races.append(forecast)

        return upcoming_races

    upcoming_race_forecasts = check_upcoming_race_forecasts()

    if upcoming_race_forecasts:
        print("Forecasts for upcoming races in the next 3 days:")
        for forecast in upcoming_race_forecasts:
            print(forecast)
    else:
        print("No races scheduled in the next 3 days.")
