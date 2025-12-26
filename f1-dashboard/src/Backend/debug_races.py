from data_loader import F1DataLoader, fastf1
import pandas as pd

loader = F1DataLoader(min_year=2010, max_year=2025)
races = loader.get_fastf1_races_for_year(2025)
print("loader races head:\n", races.head())
print("loader races tail:\n", races.tail())

if fastf1:
    sched = fastf1.get_event_schedule(2025)
    sched = sched[sched['EventName'].notna()].copy()
    sched['date'] = pd.to_datetime(sched['EventDate'], errors='coerce')
    sched['round'] = sched['RoundNumber'].astype(int)
    print("schedule head:\n", sched[['RoundNumber','EventName','date']].head())
    print("schedule tail:\n", sched[['RoundNumber','EventName','date']].tail())
