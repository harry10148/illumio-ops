import datetime
import json
import gc
import os
import sys
import logging
import tempfile
from collections import Counter
from src.utils import Colors, format_unit, safe_input
from src.i18n import t

logger = logging.getLogger(__name__)

# Refine Root Dir for State File
PKG_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(PKG_DIR)
STATE_FILE = os.path.join(ROOT_DIR, "state.json")


class Analyzer:
    def __init__(self, config_manager, api_client, reporter):
        self.cm = config_manager
        self.api = api_client
        self.reporter = reporter
        self.state = {
            "last_check": datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            "history": {},
            "alert_history": {},
            "processed_ids": []
        }
        self.load_state()

    def load_state(self):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.state.update(data)
        except FileNotFoundError:
            logger.info("State file not found, starting fresh.")
        except (json.JSONDecodeError, IOError, OSError) as e:
            logger.warning(f"Error loading state file: {e}. Starting fresh.")

    def save_state(self):
        self.state["last_check"] = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        # Prune history
        now = datetime.datetime.now(datetime.timezone.utc)
        cutoff = now - datetime.timedelta(hours=2)
        new_history = {}
        for rid, records in self.state.get("history", {}).items():
            valid = []
            for rec in records:
                try:
                    ts = datetime.datetime.strptime(rec['t'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    if ts > cutoff:
                        valid.append(rec)
                except (KeyError, ValueError):
                    pass
            if valid:
                new_history[rid] = valid
        self.state["history"] = new_history

        if len(self.state["processed_ids"]) > 2000:
            self.state["processed_ids"] = self.state["processed_ids"][-2000:]

        try:
            # Atomic write using a temporary file
            dir_name = os.path.dirname(STATE_FILE) or '.'
            fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(self.state, f, ensure_ascii=False)
                # os.replace is atomic and will overwrite the destination if it exists
                os.replace(tmp_path, STATE_FILE)
            except Exception as inner_e:
                logger.error(f"Failed to atomically write state file: {inner_e}")
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except (IOError, OSError) as e:
            logger.error(f"Error saving state: {e}")

    def calculate_mbps(self, flow):
        # Hybrid Calculation: Interval vs Total
        delta_bytes = float(flow.get("dst_dbo") or flow.get("dbo") or 0) + float(flow.get("dst_dbi") or flow.get("dbi") or 0)
        ddms = float(flow.get("ddms") or 0)

        if delta_bytes > 0 and ddms > 0:
            if ddms < 1000:
                ddms = 1000.0
            val = (delta_bytes * 8.0) / (ddms / 1000.0) / 1000000.0
            return val, "(Interval)", delta_bytes, ddms

        # Fallback to Total if Interval is 0
        tbo = float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
        tbi = float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
        total_bytes = tbo + tbi
        tdms = float(flow.get("tdms") or 0)

        if tdms < 1000:
            tdms = float(flow.get("interval_sec", 600)) * 1000

        if total_bytes > 0 and tdms > 0:
            val = (total_bytes * 8.0) / (tdms / 1000.0) / 1000000.0
            return val, "(Avg)", total_bytes, tdms

        return 0.0, "", 0.0, 0.0

    def calculate_volume_mb(self, flow):
        delta_bytes = float(flow.get("dst_dbo") or flow.get("dbo") or 0) + float(flow.get("dst_dbi") or flow.get("dbi") or 0)
        if delta_bytes > 0:
            return delta_bytes / 1024 / 1024, "(Interval)"

        tbo = float(flow.get("dst_tbo") or flow.get("tbo") or flow.get("dst_bo") or 0)
        tbi = float(flow.get("dst_tbi") or flow.get("tbi") or flow.get("dst_bi") or 0)
        return (tbo + tbi) / 1024 / 1024, "(Total)"

    def check_flow_match(self, rule, f, start_time_limit):
        # Dynamic Sliding Window Check
        if start_time_limit:
            ts_str = f.get("timestamp")
            if not ts_str and "timestamp_range" in f:
                ts_str = f["timestamp_range"].get("last_detected") or f["timestamp_range"].get("first_detected")
                
            if ts_str:
                try:
                    f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
                except ValueError:
                    try:
                        f_time = datetime.datetime.strptime(ts_str, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                    except ValueError:
                        f_time = None

                if f_time and f_time < start_time_limit:
                    return False

        # Criteria Check
        p = f.get("pd")
        raw_dec = str(f.get("policy_decision", "")).lower()
        flow_pd = -1
        if p is not None:
            flow_pd = int(p)
        elif "blocked" in raw_dec and "potentially" not in raw_dec:
            flow_pd = 2
        elif "potentially" in raw_dec:
            flow_pd = 1
        elif "allowed" in raw_dec:
            flow_pd = 0

        target_pd = rule.get("pd", 3 if rule.get("type") == "traffic" else -1)
        if target_pd != -1 and target_pd != 3 and flow_pd != target_pd:
            return False

        if rule.get("port"):
            f_port = f.get("dst_port") or f.get("service", {}).get("port")
            try:
                if not f_port or int(f_port) != int(rule["port"]):
                    return False
            except (ValueError, TypeError):
                return False

        if rule.get("proto"):
            f_proto = f.get("proto") or f.get("service", {}).get("proto")
            try:
                if not f_proto or int(f_proto) != int(rule.get("proto")):
                    return False
            except (ValueError, TypeError):
                return False

        # Labels & IPs
        if rule.get("src_label") and not self._check_flow_labels(f.get('src', {}), rule["src_label"]):
            return False
        if rule.get("dst_label") and not self._check_flow_labels(f.get('dst', {}), rule["dst_label"]):
            return False
        if rule.get("src_ip_in") and not self._check_ip_filter(f.get('src', {}), rule["src_ip_in"]):
            return False
        if rule.get("dst_ip_in") and not self._check_ip_filter(f.get('dst', {}), rule["dst_ip_in"]):
            return False

        # Excludes
        if rule.get("ex_port"):
            f_port = f.get("dst_port") or f.get("service", {}).get("port")
            try:
                if f_port and int(f_port) == int(rule["ex_port"]):
                    return False
            except (ValueError, TypeError):
                pass
        if rule.get("ex_src_label") and self._check_flow_labels(f.get('src', {}), rule["ex_src_label"]):
            return False
        if rule.get("ex_dst_label") and self._check_flow_labels(f.get('dst', {}), rule["ex_dst_label"]):
            return False
        if rule.get("ex_src_ip") and self._check_ip_filter(f.get('src', {}), rule["ex_src_ip"]):
            return False
        if rule.get("ex_dst_ip") and self._check_ip_filter(f.get('dst', {}), rule["ex_dst_ip"]):
            return False

        return True

    def _check_flow_labels(self, flow_side, filter_str):
        if not filter_str:
            return True
        try:
            fk, fv = filter_str.split('=')
            for l in flow_side.get('workload', {}).get('labels', []):
                if l.get('key') == fk.strip() and l.get('value') == fv.strip():
                    return True
            return False
        except ValueError:
            return False

    def _check_ip_filter(self, flow_side, filter_val):
        if not filter_val:
            return True
        if flow_side.get('ip') == filter_val:
            return True
        for ipl in flow_side.get('ip_lists', []):
            if ipl.get('name') == filter_val:
                return True
        return False

    def get_traffic_details_key(self, flow):
        src = flow.get('src', {})
        dst = flow.get('dst', {})
        svc = flow.get('service', {})
        s_name = src.get('workload', {}).get('name') or src.get('ip', 'N/A')
        d_name = dst.get('workload', {}).get('name') or dst.get('ip', 'N/A')
        port = svc.get('port', 'All') or flow.get('dst_port', 'All')
        return f"{s_name} -> {d_name} [{port}]"

    def run_analysis(self):
        logger.info("Starting analysis cycle.")
        # 1. Health Check
        if self.cm.config["settings"].get("enable_health_check", True):
            print(f"{t('checking_pce_health')}...", end=" ", flush=True)
            status, msg = self.api.check_health()
            if status != 200:
                print(f"{Colors.FAIL}{t('status_error')}{Colors.ENDC}")
                logger.warning(f"PCE health check failed: {status} - {msg[:200]}")
                self.reporter.add_health_alert({
                    "time": datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    "status": str(status),
                    "details": msg[:200]
                })
            else:
                print(f"{Colors.GREEN}{t('status_ok')}{Colors.ENDC}")
                logger.info("PCE health check OK.")

        # 2. Events
        print(f"{t('checking_events')}...")
        events = self.api.fetch_events(self.state["last_check"])
        if events:
            print(t('found_events', count=len(events)))
            logger.info(f"Found {len(events)} events.")
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            for rule in [r for r in self.cm.config["rules"] if r["type"] == "event"]:
                # Enhanced filtering with status and severity
                matches = []
                for e in events:
                    if rule["filter_value"] != e.get("event_type"):
                        continue
                        
                    # Status Filter
                    r_status = rule.get("filter_status", "all")
                    if r_status != "all" and e.get("status") != r_status:
                        continue
                        
                    # Severity Filter
                    r_sev = rule.get("filter_severity", "all")
                    if r_sev != "all" and e.get("severity") != r_sev:
                        continue
                        
                    matches.append(e)

                # Event History Logic for 'count' threshold
                if matches:
                    rid = str(rule["id"])
                    if rid not in self.state["history"]:
                        self.state["history"][rid] = []
                    self.state["history"][rid].append({"t": now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'), "c": len(matches)})

                # Check Threshold
                count_val = len(matches)
                if rule["threshold_type"] == "count":
                    win_minutes = rule.get("threshold_window", 10)
                    win_start = now_utc - datetime.timedelta(minutes=win_minutes)
                    count_val = sum(
                        rec['c'] for rec in self.state.get("history", {}).get(str(rule["id"]), [])
                        if datetime.datetime.strptime(rec['t'], '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc) > win_start
                    )

                if count_val >= rule["threshold_count"] and count_val > 0:
                    if self._check_cooldown(rule):
                        self.reporter.add_event_alert({
                            "time": matches[0].get("timestamp") if matches else "N/A",
                            "rule": rule["name"],
                            "desc": rule.get("desc"),
                            "severity": matches[0].get("severity", "info") if matches else "info",
                            "count": count_val,
                            "source": matches[0].get("created_by", {}).get("agent", {}).get("hostname", "System") if matches else "N/A",
                            "raw_data": matches[:5]
                        })

        # 3. Traffic
        tr_rules = [r for r in self.cm.config["rules"] if r["type"] in ["traffic", "bandwidth", "volume"]]
        if tr_rules:
            max_win = max([r.get('threshold_window', 10) for r in tr_rules])
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            start_dt = now_utc - datetime.timedelta(minutes=max_win + 2)

            traffic_stream = self.api.execute_traffic_query_stream(
                start_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
                now_utc.strftime('%Y-%m-%dT%H:%M:%SZ'),
                ["blocked", "potentially_blocked", "allowed"]
            )

            if traffic_stream:
                rule_results = {r['id']: {'max_val': 0.0, 'top_matches': []} for r in tr_rules}

                count_processed = 0
                for f in traffic_stream:
                    count_processed += 1

                    bw_val, bw_note, _, _ = self.calculate_mbps(f)
                    vol_val, vol_note = self.calculate_volume_mb(f)
                    conn_val = int(f.get("num_connections") or f.get("count", 1))

                    for rule in tr_rules:
                        rid = rule['id']
                        r_win = rule.get("threshold_window", 10)
                        r_start = now_utc - datetime.timedelta(minutes=r_win)

                        if not self.check_flow_match(rule, f, r_start):
                            continue

                        res = rule_results[rid]

                        if rule["type"] == "bandwidth":
                            if bw_val > res['max_val']:
                                res['max_val'] = bw_val
                            if bw_val > float(rule.get("threshold_count", 0)):
                                f_copy = f.copy()
                                f_copy['_metric_val'] = bw_val
                                f_copy['_metric_fmt'] = f"{format_unit(bw_val, 'bandwidth')} {bw_note}"
                                res['top_matches'].append(f_copy)

                        elif rule["type"] == "volume":
                            res['max_val'] += vol_val
                            f_copy = f.copy()
                            f_copy['_metric_val'] = vol_val
                            f_copy['_metric_fmt'] = f"{format_unit(vol_val, 'volume')} {vol_note}"
                            res['top_matches'].append(f_copy)

                        else:  # Traffic Count
                            res['max_val'] += conn_val
                            f_copy = f.copy()
                            f_copy['_metric_val'] = conn_val
                            f_copy['_metric_fmt'] = str(conn_val)
                            res['top_matches'].append(f_copy)

                print(t('found_traffic', count=count_processed))
                logger.info(f"Processed {count_processed} traffic flows.")

                # Check Triggers
                for rule in tr_rules:
                    rid = rule['id']
                    res = rule_results[rid]
                    val = res['max_val']
                    threshold = float(rule.get("threshold_count", 0))

                    is_trigger = False
                    if rule["type"] == "bandwidth":
                        if len(res['top_matches']) > 0:
                            is_trigger = True
                    else:
                        if val >= threshold:
                            is_trigger = True

                    if is_trigger and self._check_cooldown(rule):
                        res['top_matches'].sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
                        top_10 = res['top_matches'][:10]

                        ctr = Counter([self.get_traffic_details_key(m) for m in top_10])
                        details = "<br>".join([f"{k}: {v}" for k, v in ctr.most_common(10)])

                        alert_data = {
                            "rule": rule["name"],
                            "count": f"{val:.2f}" if rule['type'] != 'traffic' else str(int(val)),
                            "criteria": self._build_criteria_str(rule),
                            "details": details,
                            "raw_data": top_10
                        }

                        if rule["type"] in ["bandwidth", "volume"]:
                            self.reporter.add_metric_alert(alert_data)
                        else:
                            self.reporter.add_traffic_alert(alert_data)

        self.save_state()
        logger.info("Analysis cycle completed.")
        gc.collect()

    def _check_cooldown(self, rule):
        rid = str(rule["id"])
        now_utc = datetime.datetime.now(datetime.timezone.utc)
        last_alert = self.state.get("alert_history", {}).get(rid)

        cd_minutes = rule.get("cooldown_minutes", rule.get("threshold_window", 10))

        if last_alert:
            try:
                last_dt = datetime.datetime.strptime(last_alert, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                if (now_utc - last_dt).total_seconds() < (cd_minutes * 60):
                    print(f"{Colors.WARNING}{t('alert_cooldown', rule=rule['name'])}{Colors.ENDC}")
                    logger.info(f"Rule '{rule['name']}' in cooldown.")
                    return False
            except ValueError:
                pass

        print(f"{Colors.FAIL}{t('alert_trigger', rule=rule['name'])}{Colors.ENDC}")
        logger.warning(f"Alert triggered: {rule['name']}")
        if "alert_history" not in self.state:
            self.state["alert_history"] = {}
        self.state["alert_history"][rid] = now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')
        return True

    def _build_criteria_str(self, rule):
        crit = [f"Threshold: > {rule['threshold_count']}"]
        if rule.get('port'):
            crit.append(f"Port:{rule['port']}")
        return ", ".join(crit)

    def query_flows(self, params: dict):
        """
        Generic traffic flow query utilizing identical metrics logic to run_debug_mode.
        params schema:
        {
          "start_time": "2026-02-23T00:00:00Z",
          "end_time": "2026-02-23T23:59:59Z",
          "policy_decisions": ["blocked", "allowed"],
          "sort_by": "bandwidth", # bandwidth, volume, connections
          "search": "192.168.1.1" # optional text filter
        }
        """
        start_time = params.get("start_time")
        end_time = params.get("end_time")
        pds = params.get("policy_decisions", ["blocked", "potentially_blocked", "allowed"])
        
        strict_pd: set[str] = set()
        for p in pds:
            if p == "potentially_blocked": strict_pd.add("potentially_blocked")
            elif p == "blocked": strict_pd.add("blocked")
            elif p == "allowed": strict_pd.add("allowed")
        
        traffic_stream = self.api.execute_traffic_query_stream(start_time, end_time, pds)
        if not traffic_stream:
            return []

        search_query = params.get("search", "").lower()

        rule = {
            "type": "bandwidth",
            "pd": -1,
            "port": params.get("port"), "proto": params.get("proto"),
            "src_label": params.get("src_label"), "dst_label": params.get("dst_label"),
            "src_ip_in": params.get("src_ip_in"), "dst_ip_in": params.get("dst_ip_in"),
            "ex_port": params.get("ex_port"),
            "ex_src_label": params.get("ex_src_label"), "ex_dst_label": params.get("ex_dst_label"),
            "ex_src_ip": params.get("ex_src_ip"), "ex_dst_ip": params.get("ex_dst_ip")
        }

        now_dt = datetime.datetime.now(datetime.timezone.utc)
        try:
            start_dt = datetime.datetime.strptime(start_time, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
        except:
            start_dt = now_dt - datetime.timedelta(minutes=30)
            
        matches = []
        sort_by = params.get("sort_by", "bandwidth")
        rule["type"] = sort_by if sort_by in ["bandwidth", "volume"] else "connections"

        for f in traffic_stream:
            if strict_pd and f.get("policy_decision") not in strict_pd:
                continue

            if not self.check_flow_match(rule, f, start_dt):
                continue
                
            src = f.get('src', {})
            dst = f.get('dst', {})
            svc = f.get('service', {})

            s_name = src.get('workload', {}).get('name') or src.get('ip', 'N/A')
            d_name = dst.get('workload', {}).get('name') or dst.get('ip', 'N/A')
            port = svc.get('port', 'All') or f.get('dst_port', 'All')

            # Detailed Attribution
            s_proc = (src.get('process_name') or "").lower()
            s_user = (src.get('user_name') or "").lower()
            d_proc = (dst.get('process_name') or svc.get('process_name') or "").lower()
            d_user = (dst.get('user_name') or svc.get('user_name') or "").lower()
            svc_name = (svc.get("name") or "").lower()

            if search_query:
                s_ip = str(src.get('ip', '')).lower()
                d_ip = str(dst.get('ip', '')).lower()
                
                matches_search = (
                    search_query in s_name.lower() or 
                    search_query in d_name.lower() or
                    search_query in s_ip or 
                    search_query in d_ip or
                    search_query == str(port).lower() or
                    search_query in s_proc or
                    search_query in s_user or
                    search_query in d_proc or
                    search_query in d_user or
                    search_query in svc_name
                )
                
                if not matches_search:
                    continue

            f_copy = f.copy()
            
            # Format Protocol Name
            proto = f.get('proto') or svc.get('proto', '')
            try:
                p_int = int(proto)
                if p_int == 6: proto = "TCP"
                elif p_int == 17: proto = "UDP"
                elif p_int == 1: proto = "ICMP"
            except: pass

            f_copy['source'] = {
                "name": s_name,
                "ip": src.get('ip'),
                "href": src.get('workload', {}).get('href'),
                "labels": src.get('workload', {}).get('labels', []),
                "process": src.get('process_name') or "",
                "user": src.get('user_name') or ""
            }
            f_copy['destination'] = {
                "name": d_name,
                "ip": dst.get('ip'),
                "href": dst.get('workload', {}).get('href'),
                "labels": dst.get('workload', {}).get('labels', []),
                "process": dst.get('process_name') or svc.get('process_name') or "",
                "user": dst.get('user_name') or svc.get('user_name') or ""
            }
            f_copy['service'] = {
                "port": port,
                "proto": proto,
                "name": svc.get("name") or getattr(svc, 'name', '') or f.get("sn") or ""
            }

            bw_val, bw_note, _, _ = self.calculate_mbps(f)
            vol_val, vol_note = self.calculate_volume_mb(f)
            conn_val = int(f.get("num_connections") or f.get("count", 1))

            if rule["type"] == "bandwidth":
                f_copy['_metric_val'] = bw_val
            elif rule["type"] == "volume":
                f_copy['_metric_val'] = vol_val
            else:
                f_copy['_metric_val'] = conn_val
                
            f_copy["max_bandwidth_mbps"] = bw_val
            f_copy["total_volume_mb"] = vol_val
            f_copy["total_connections"] = conn_val
            
            f_copy["formatted_bandwidth"] = f"{format_unit(bw_val, 'bandwidth')} {bw_note}".strip()
            f_copy["formatted_volume"] = f"{format_unit(vol_val, 'volume')} {vol_note}".strip()
            f_copy["formatted_connections"] = f"{conn_val}"
            
            ts = f.get('timestamp_range', {})
            f_copy["first_seen"] = ts.get('first_detected')
            f_copy["last_seen"] = ts.get('last_detected')
            f_copy["policy_decision"] = f.get("policy_decision")

            matches.append(f_copy)

        matches.sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
        return matches[:500]

    def run_debug_mode(self, mins=None, pd_sel=None):
        print(f"\n{Colors.HEADER}{t('debug_mode_title')}{Colors.ENDC}")

        # Auto-detect minutes if not provided
        max_win = 10
        for r in self.cm.config['rules']:
            w = r.get('threshold_window', 10)
            if w > max_win:
                max_win = w

        if mins is None:
            mins_input = safe_input(t('query_past_mins'), int, allow_cancel=True)
            if mins_input is None:  # 使用者按 0 返回
                return
            if mins_input == '' or mins_input == 0:  # 使用者按 Enter 或輸入 0，使用預設
                mins = max_win + 2
            else:
                mins = int(mins_input)

        now = datetime.datetime.now(datetime.timezone.utc)
        start_dt = now - datetime.timedelta(minutes=mins)
        start_str = start_dt.strftime('%Y-%m-%dT%H:%M:%SZ')
        end_str = now.strftime('%Y-%m-%dT%H:%M:%SZ')

        # 1. Fetch Events
        print(f"\n{Colors.CYAN}[1/2] {t('checking_events')}...{Colors.ENDC}")
        events = self.api.fetch_events(start_str)
        print(f"  -> {t('found_events', count=len(events))}")

        # 2. Fetch Traffic
        print(f"\n{Colors.CYAN}[2/2] {t('submitting_query', start=start_dt.strftime('%H:%M'), end=now.strftime('%H:%M'))}{Colors.ENDC}")
        
        # Determine PDs for traffic query
        if pd_sel is None:
            print(f"\n{t('policy_decision')}")
            print(f"1. {t('pd_1_blocked_only', default='Blocked Only')}")
            print(f"2. {t('pd_2_allowed_only', default='Allowed Only')}")
            print(f"3. {t('pd_3_all', default='All (Blocked + Potential + Allowed)')} [{t('nav_default', default='Default')}]")
            pd_input = safe_input(t('please_select'), int, range(0, 4), allow_cancel=True)
            if pd_input is None: return  # 使用者按 0 返回
            if pd_input == '' or pd_input == 0:
                pd_sel = 3  # 預設: All
            else:
                pd_sel = int(pd_input)

        pds = ["blocked", "potentially_blocked", "allowed"]
        if pd_sel == 1: pds = ["blocked"]
        elif pd_sel == 2: pds = ["allowed"]

        traffic_gen = self.api.execute_traffic_query_stream(start_str, end_str, pds)
        traffic = list(traffic_gen) if traffic_gen else []
        print(f"  -> {t('fetched_records', count=len(traffic), mins=mins)}")

        print(f"\n{Colors.HEADER}{t('simulation_report')}{Colors.ENDC}")

        for rule in self.cm.config["rules"]:
            rtype = rule.get("type", "event")
            r_label = t('event_rule') if rtype == "event" else t('traffic_rule')
            print(f"\n{Colors.CYAN}--- {r_label}: {rule['name']} ({rtype.upper()}) ---{Colors.ENDC}")
            
            rule_win = rule.get("threshold_window", 10)
            rule_start = now - datetime.timedelta(minutes=rule_win)
            matches = []

            if rtype == "event":
                # Event Logic
                for e in events:
                    # Time check for events
                    pts = e.get('timestamp')
                    e_time = None
                    if pts:
                        try: e_time = datetime.datetime.strptime(pts, '%Y-%m-%dT%H:%M:%S.%fZ').replace(tzinfo=datetime.timezone.utc)
                        except ValueError:
                            try: e_time = datetime.datetime.strptime(pts, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=datetime.timezone.utc)
                            except ValueError: pass

                    if e_time and e_time < rule_start: continue
                    
                    if rule["filter_value"] != e.get("event_type"): continue
                    
                    # Filters
                    r_status = rule.get("filter_status", "all")
                    if r_status != "all" and e.get("status") != r_status: continue
                    r_sev = rule.get("filter_severity", "all")
                    if r_sev != "all" and e.get("severity") != r_sev: continue
                    
                    matches.append(e)
                
                print(t('time_filter_results', total=len(events), win=rule_win, rem=len(matches)))
                val = len(matches)
                threshold = float(rule.get("threshold_count", 1))
                is_trigger = val >= threshold

                status = f"{Colors.FAIL}{t('would_trigger')}{Colors.ENDC}" if is_trigger else f"{Colors.GREEN}{t('pass')}{Colors.ENDC}"
                print(t('eval_result', status=status, threshold=int(threshold)))

                if matches:
                    print(t('samples_top10'))
                    for i, m in enumerate(matches[:10]):
                        msg = m.get('message', 'No message')
                        m_status = m.get('status', 'N/A')
                        m_ts = m.get('timestamp', 'N/A')[-13:-1] # Show HH:MM:SS.ms
                        print(f"     [{i+1}] {m_ts} | {m_status} | {msg[:80]}")

            else:
                # Traffic / BW / Vol Logic
                for f in traffic:
                    if self.check_flow_match(rule, f, rule_start):
                        f_copy = f.copy()
                        if rtype == "bandwidth":
                            v, note, _, _ = self.calculate_mbps(f)
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'bandwidth')} {note}"
                        elif rtype == "volume":
                            v, note = self.calculate_volume_mb(f)
                            f_copy['_metric_val'] = v
                            f_copy['_metric_fmt'] = f"{format_unit(v, 'volume')} {note}"
                        else:
                            c = int(f.get("num_connections") or f.get("count", 1))
                            f_copy['_metric_val'] = c
                            f_copy['_metric_fmt'] = str(c)
                        matches.append(f_copy)

                print(t('time_filter_results', total=len(traffic), win=rule_win, rem=len(matches)))
                val = 0.0
                if rtype == "bandwidth":
                    val = max([m['_metric_val'] for m in matches]) if matches else 0.0
                    print(t('calc_max_bw', val=val))
                elif rtype == "volume":
                    val = sum([m['_metric_val'] for m in matches])
                    print(t('calc_sum_vol', val=val))
                else:
                    val = sum([m['_metric_val'] for m in matches])
                    print(t('calc_sum_count', val=int(val)))

                threshold = float(rule.get("threshold_count", 0))
                is_trigger = val > threshold if rtype == "bandwidth" else val >= threshold
                
                status = f"{Colors.FAIL}{t('would_trigger')}{Colors.ENDC}" if is_trigger else f"{Colors.GREEN}{t('pass')}{Colors.ENDC}"
                print(t('eval_result', status=status, threshold=threshold))

                if matches:
                    print(t('samples_top10'))
                    if rtype in ["bandwidth", "volume"]:
                        matches.sort(key=lambda x: x.get('_metric_val', 0), reverse=True)
                    for i, m in enumerate(matches[:10]):
                        key = self.get_traffic_details_key(m)
                        print(f"     [{i+1}] {key} Value: {m.get('_metric_fmt')} (PD:{m.get('policy_decision')})")

        # Handle GUI/Non-interactive mode (stdin/stdout capture)
        is_gui = hasattr(sys.stdout, 'getvalue')
        
        if not is_gui:
            save_sel = safe_input(f"\n{t('save_debug_query')}", str, allow_cancel=True)
            if save_sel and save_sel.lower() == 'y':
                dump = {
                    "timestamp": now.strftime('%Y-%m-%dT%H:%M:%SZ'),
                    "mins": mins,
                    "events_count": len(events),
                    "traffic_count": len(traffic),
                    "events": events,
                    "traffic": traffic
                }
                path = os.path.join(ROOT_DIR, "debug_dump.json")
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(dump, f, indent=2, ensure_ascii=False)
                print(f"\n{Colors.GREEN}{t('file_saved', path=path)}{Colors.ENDC}")

        if not is_gui:
            print(f"\n{Colors.GREEN}{t('debug_done')}{Colors.ENDC}")
