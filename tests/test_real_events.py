from src.config import ConfigManager
from src.api_client import ApiClient
import datetime

cm = ConfigManager()
cm.load()
api = ApiClient(cm)

end_date = datetime.datetime.utcnow()
start_date = end_date - datetime.timedelta(days=7)

start_str = start_date.isoformat() + "Z"
end_str = end_date.isoformat() + "Z"

print(f"Fetching events from {start_str} to {end_str}...")
events = api.fetch_events(start_time_str=start_str, end_time_str=end_str, max_results=100)

print(f"Returned {len(events)} events.")
if events:
    print(events[0])
