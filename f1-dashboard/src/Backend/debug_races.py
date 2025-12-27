from data_loader import F1DataLoader, fastf1
import pandas as pd

loader = F1DataLoader(min_year=2010, max_year=2025)
races = loader.get_fastf1_races_for_year(2025)
if races is not None:
    print("loader races head:\n", races.head())
    print("loader races tail:\n", races.tail())
else:
    print("No races returned by FastF1 loader")

if fastf1:
    sched = fastf1.get_event_schedule(2025)
    sched_df = pd.DataFrame(sched[sched['EventName'].notna()].copy())
    sched_df['date'] = pd.to_datetime(sched_df['EventDate'], errors='coerce')
    sched_df['round'] = sched_df['RoundNumber'].astype(int)
    print("schedule head:\n", sched_df[['RoundNumber','EventName','date']].head())
    print("schedule tail:\n", sched_df[['RoundNumber','EventName','date']].tail())
