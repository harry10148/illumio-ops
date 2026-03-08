import json
import os
import sys
from src.config import ConfigManager
from src.api_client import ApiClient

def main():
    cm = ConfigManager()
    api = ApiClient(cm)
    
    print("Fetching last 24h events...")
    import datetime
    start_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=24)).strftime('%Y-%m-%dT%H:%M:%SZ')
    events = api.fetch_events(start_time)
    
    if not events:
        print("No events found.")
        return
        
    print(f"Found {len(events)} events.")
    
    # Save to file for inspection
    with open('debug_events.json', 'w', encoding='utf-8') as f:
        json.dump(events, f, indent=2, ensure_ascii=False)
        
    print("Events saved to debug_events.json")
    
    # Analyze login related events
    login_events = [e for e in events if 'login' in e.get('event_type', '').lower() or 'auth' in e.get('event_type', '').lower()]
    print(f"\nLogin/Auth 관련 이벤트 ({len(login_events)}개):")
    for e in login_events:
        print(f"- Type: {e.get('event_type')}, Status: {e.get('status')}, Severity: {e.get('severity')}, Time: {e.get('timestamp')}")

if __name__ == "__main__":
    # Add project root to sys.path
    project_root = os.getcwd()
    if project_root not in sys.path:
        sys.path.append(project_root)
    main()
