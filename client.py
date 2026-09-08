#last version
import asyncio
import signal
from aiocoap import *
from aiocoap import resource
import aiocoap.error
import cbor2
import json
import os
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from datetime import datetime, timedelta
from collections import deque

from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

#this identify critical threshold for the alarm
HR_CRITICAL=100
RR_CRITICAL=24
SPO2_CRITICAL=92

#this identify danger threshold for the activation of O2 pump
SPO2_DANGER=85
WINDOW_SIZE=5
CONFIRM_COUNT=4


IDLE_TIMEOUT_MULTIPLIER = 3
IDLE_TIMEOUT_MIN = 10       
IDLE_TIMEOUT_DEFAULT = 30    

class PatientState:
    def __init__(self, patient_name):
        self.patient_name = patient_name
        self.window=deque(maxlen=WINDOW_SIZE)
        self.prev_decision="insufficient_data"
        self.n_stable=0

    def add_reading(self,hr, rr,spo2):
        n_criteria=sum([hr>=HR_CRITICAL, rr>=RR_CRITICAL, spo2<=SPO2_CRITICAL])
        self.window.append({
            "heart_rate": hr,
            "respiration_rate": rr,
            "spo2": spo2,
            "critical": n_criteria>=2,
            "danger": spo2<=SPO2_DANGER
        })

    def evaluate_patient_condition(self):
        if(len(self.window)>=2):
            last_two=list(self.window)[-2:]
            if all(reading["danger"] for reading in last_two):
                return "activate_pump"
        if(len(self.window)<WINDOW_SIZE):
            return "insufficient_data"
        critical_count=sum(reading["critical"] for reading in self.window)>=CONFIRM_COUNT
        if critical_count:
            return "activate_alarm"
        all_stable=all((not reading["critical"])and (not reading["danger"]) for reading in self.window)
        if all_stable:
            return "stable"
        return self.prev_decision
        
patient_states: dict[str, PatientState] = {}

async def hydrate_patient_state(query_api, bucket, org, patient_name, state):
    query = f"""
    from(bucket: "{bucket}")
      |> range(start: -75s)
      |> filter(fn: (r) => r["_measurement"] == "patient_vitals")
      |> filter(fn: (r) => r["patient_name"] == "{patient_name}")
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
      |> sort(columns: ["_time"], desc: false)
      |> tail(n: {WINDOW_SIZE})
    """
    try:
        tables = await query_api.query(query, org=org)
        for table in tables:
            for record in table.records:
                hr = record.values.get("heart_rate")
                rr = record.values.get("respiration_rate")
                spo2 = record.values.get("spo2")
                if None not in (hr, rr, spo2):
                    state.add_reading(hr, rr, spo2)
        print(f"[HYDRATION] Pre-loaded {len(state.window)} historical readings for {patient_name}")
    except Exception as e:
        print(f"[HYDRATION ERROR] Failed to fetch data for {patient_name}: {e}")

async def send_coap_command(protocol,patient_name,remote_ipv6,resource,state_val):
    if(not remote_ipv6):
        print("[REMOTE ERROR] no ipv6 configured for this device")
        return False
    uri=f"coap://[{remote_ipv6}]/{resource}"
    payload=str(state_val).encode("utf-8")
    request=Message(code=PUT,uri=uri,payload=payload)
    try:
        response=await protocol.request(request).response
        print(f"[REMOTE] Resource'{resource}'on[{remote_ipv6}] assciated to [{patient_name}] set on {state_val} -> Coap response: {response.code}")
        return response.code.is_successful()
    except Exception as e:
        print(f"[REMOTE] cannot contact {uri}: {e}")
        return False
    
async def write_decision_event(write_api, bucket, org, patient_name, decision, hr, rr, spo2,status):
    point = (
        Point("panic_decisions")
        .tag("patient_name", patient_name)
        .field("decision", decision)
        .field("status",status)
        .field("heart_rate", int(hr))
        .field("respiration_rate", int(rr))
        .field("spo2", int(spo2))
    )
    try:
        await write_api.write(bucket=bucket, org=org, record=point)
    except Exception as e:
        print(f"[INFLUXDB ERROR] Failed to write decision event for {patient_name}: {e}") 

async def evaluate_and_act(protocol,state,sensor_id,hr,rr,spo2,write_api,bucket,org,actuator_ipv6=None,sensor_ipv6=None):
    state.add_reading(hr,rr,spo2)
    old_decision=state.prev_decision
    decision=state.evaluate_patient_condition()
    state.prev_decision=decision
    for i, reading in enumerate(state.window):
        print(f"  [{i+1}/{len(state.window)}] Critical: {reading['critical']} | Danger: {reading['danger']}")

    if(decision=="stable"):
        state.n_stable=state.n_stable+1
    else:
        state.n_stable=0
    if (state.n_stable==5):
        send_command=True
        state.n_stable=0
    else:
        send_command=False
    should_send_commands=(decision!=old_decision)or(send_command)
    
    if(should_send_commands):
        match decision:
            case "activate_pump":
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "pump", "1")
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "alarm", "1")
                await send_coap_command(protocol,state.patient_name,sensor_ipv6, "vital_signs", "1")
            case "activate_alarm":
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "alarm", "1")
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "pump", "0")
                await send_coap_command(protocol,state.patient_name,sensor_ipv6, "vital_signs", "1")
                    
            case "stable":
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "alarm", "0")
                await send_coap_command(protocol,state.patient_name,actuator_ipv6, "pump", "0")
                await send_coap_command(protocol,state.patient_name,sensor_ipv6, "vital_signs", "0")
            case "insufficient_data":
                print("data is not sufficient")        
            case _:
                print("Unknown decision")   
        if decision !="insufficient_data":
            match(decision):
                case "activate_pump":
                    status="danger"
                case "activate_alarm":
                    status="critical"
                case _:
                    status="stable"
                    decision="return_to_normal"   
            await write_decision_event(write_api,bucket, org, state.patient_name, decision, hr, rr, spo2,status)
    return decision     
       
def load_configuration(filename="config.json"):
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Configuration file '{filename}' not found!")
    with open(filename, "r") as f:
        return json.load(f)

async def write_to_influx(write_api, bucket, org, patient_name, cbor_data, reception_time,payload_size):
    try:
        vitals_list = extract_vitals(cbor_data)
        sensor_bn = str(cbor_data.get('bn', 'unknown'))
        size_point = Point("network_metrics") \
            .tag("patient_name", patient_name) \
            .tag("sensor_bn", sensor_bn) \
            .time(reception_time) \
            .field("payload_size_bytes", payload_size)
        await write_api.write(bucket="payload", org=org, record=size_point)
        interval=int(cbor_data.get('interval', 30))
        total_readings=len(vitals_list)
        historical_time = reception_time
        points = []
        for i in range(len(vitals_list) - 1, -1, -1):
            hr, rr, spo2, interval_sec = vitals_list[i]

            point = Point("patient_vitals") \
                .tag("patient_name", patient_name) \
                .tag("sensor_bn", sensor_bn) \
                .time(historical_time) \
                .field("heart_rate", int(hr)) \
                .field("respiration_rate", int(rr)) \
                .field("spo2", int(spo2))  
            points.append(point)

            if i > 0:
                prev_interval = vitals_list[i-1][3]
                historical_time -= timedelta(seconds=prev_interval)

        for point in reversed(points):
            await write_api.write(bucket=bucket, org=org, record=point)            
    except Exception as e:
        print(f"[INFLUXDB ERROR] Failed to write data for {patient_name}: {e}")

def extract_vitals(cbor_data):
    events=cbor_data.get('e',[])
    readings=[]
    current={}
    for event in events:
        name = event.get('n')
        value = event.get('v')
        if name == "heartRate":
            current["hr"] = value
        elif name == "resRate":
            current["rr"] = value
        elif name == "spo2":
            current["spo2"] = value
        elif name == "interval":
            current["interval"] = value
        if {"hr", "rr", "spo2","interval"} <= current.keys():
            readings.append((current["hr"], current["rr"], current["spo2"], current["interval"]))
            current = {}
    return readings
       
async def observe_sensor(protocol, app_name, sensor_id, patient_name, ipv6, write_api, read_api, influx_bucket, influx_org, decision_bucket, actuator_ipv6=None):
    resource_path = "vital_signs"
    uri = f"coap://[{ipv6}]/{resource_path}"
    state = patient_states.setdefault(patient_name, PatientState(patient_name))
    last_known_interval = IDLE_TIMEOUT_DEFAULT

    try:
        await asyncio.wait_for(
            hydrate_patient_state(read_api, influx_bucket, influx_org, patient_name, state),
            timeout=3.0
        )
    except asyncio.TimeoutError:
        print(f"[HYDRATION WARNING] Timeout while fetching data for {patient_name}")

    async def handle_packet(payload, label):
        nonlocal last_known_interval
        if len(payload) == 0:
            return
        timezone_italy = ZoneInfo("Europe/Rome")
        reception_time = datetime.now(timezone_italy)
        try:
            cbor_data = cbor2.loads(payload)
        except Exception as e:
            print(f"[CBOR ERROR] Payload malformed from {patient_name} ignored: {e}")
            return
        last_known_interval = int(cbor_data.get('interval', last_known_interval))
        print(f"\n=== {label} [{app_name}] ===")
        print(f"Patient: {patient_name} (ID: {sensor_id}) | Received at: {reception_time}")
        print(f"Decoded CBOR: {json.dumps(cbor_data, indent=2)}")
        await write_to_influx(write_api, influx_bucket, influx_org, patient_name, cbor_data, reception_time, len(payload))
        readings = extract_vitals(cbor_data)
        if len(readings) > 1:
            print(f"[BUFFER] Packet with {len(readings)} buffered readings received from {patient_name}")
        for hr, rr, spo2, interval in readings:
            decision = await evaluate_and_act(
                protocol, state, sensor_id, hr, rr, spo2,
                write_api, decision_bucket, influx_org, actuator_ipv6, ipv6
            )
            print(f"[DECISION] {patient_name}: {decision}")

    retry_delay = 5
    current_pr = None
    try:
        while True:
            pr = None
            try:
                print(f"[OBSERVE] Connecting to {patient_name} ({ipv6})...")
                request = Message(code=GET, uri=uri, observe=0)
                pr = protocol.request(request)
                current_pr = pr

                first_response = await asyncio.wait_for(pr.response, timeout=60.0)

                if not first_response.code.is_successful():
                    print(f"[ERROR] {patient_name} (Node {sensor_id}) replied with: {first_response.code}, retrying in {retry_delay}s...")
                    pr.observation.cancel()
                    await asyncio.sleep(retry_delay)
                    continue

                print(f"[OBSERVE] Observation active for {patient_name}, waiting for notifications...")
                await handle_packet(first_response.payload, "FIRST RESPONSE")

                observation_iter = pr.observation.__aiter__()
                try:
                    while True:
                        idle_timeout = max(IDLE_TIMEOUT_MIN, last_known_interval * IDLE_TIMEOUT_MULTIPLIER)
                        try:
                            packet = await asyncio.wait_for(
                                observation_iter.__anext__(),
                                timeout=idle_timeout,
                            )
                        except StopAsyncIteration:
                            break
                        await handle_packet(packet.payload, "NOTIFICATION")
                except asyncio.TimeoutError:
                    print(f"[WATCHDOG] No notification from {patient_name} in {idle_timeout}s "
                          f"(last known reporting interval: {last_known_interval}s) observer likely "
                          f"dropped server-side after a network blip. Resubscribing...")
                    if pr is not None:
                        pr.observation.cancel()
                    await asyncio.sleep(1) 
                    continue
                except (aiocoap.error.RequestTimedOut, aiocoap.error.NetworkError) as e:
                    print(f"[WATCHDOG] Transfer broken by network blip for {patient_name}: {e}. Reconnecting immediately...")
                    if pr is not None:
                        pr.observation.cancel()
                    await asyncio.sleep(1) 
                    continue

                print(f"[OBSERVE] Observation ended for {patient_name}, reconnecting in {retry_delay}s...")
                await asyncio.sleep(retry_delay)

            except asyncio.TimeoutError:
                print(f"[OBSERVE] Timeout connecting to {patient_name} ({ipv6}), retrying in {retry_delay}s...")
                if pr is not None:
                    pr.observation.cancel()
                await asyncio.sleep(retry_delay)
            except Exception as e:
                print(f"[OBSERVE] Error for {patient_name} ({ipv6}): {e}, retrying in {retry_delay}s...")
                if pr is not None:
                    try:
                        pr.observation.cancel()
                    except Exception:
                        pass
                await asyncio.sleep(retry_delay)
    except asyncio.CancelledError:
        if current_pr is not None:
            try:
                current_pr.observation.cancel()
                print(f"[SHUTDOWN] Deregistered observation for {patient_name}")
            except Exception:
                pass
        raise

class PingResource(resource.Resource):
    async def render_post(self, request):
        return Message(code=CHANGED, payload=b"ACK")

async def main():
    try:
        config = load_configuration()
        app_name = config.get("applicationName", "Unknown Application")
        patients_cfg=config.get("patients",[])
        influx_cfg = config.get("influxdb", {})
    except Exception as e:
        print(f"Error loading the configuration file: {e}")
        return

    if not patients_cfg:
        print("No patients configured configured in config.json.")
        return
        
    load_dotenv()
    
    influx_client = InfluxDBClientAsync(
        url=influx_cfg.get("url"),
        token=os.getenv("INFLUX_TOKEN"),
        org=influx_cfg.get("org")
    )
    write_api = influx_client.write_api()
    read_api = influx_client.query_api()
    decisions_bucket=influx_cfg.get("decision_bucket")

    print(f"Starting '{app_name}' monitoring system...")
    print(f"Connected to InfluxDB at {influx_cfg.get('url')}")
    print(f"Configured to monitor {len(patients_cfg)} patient(s) concurrently.\n")

    site=resource.Site()
    site.add_resource(["ping"], PingResource())
    protocol = await Context.create_server_context(site)

    try:
        tasks=[]
        for patient in patients_cfg:
            patient_name=patient.get("patient_name")
            sensor_nodes=patient.get("sensor_nodes",[])
            actuator_nodes=patient.get("actuator_nodes",[])
            actuator_ipv6 = actuator_nodes[0].get("ipv6") if actuator_nodes else None
            for sensor in sensor_nodes:
                tasks.append(observe_sensor(
                    protocol,
                    app_name,
                    sensor.get("sensor_id"),
                    patient_name,
                    sensor.get("ipv6"),
                    write_api,
                    read_api,
                    influx_cfg.get("bucket"),
                    influx_cfg.get("org"),
                    decisions_bucket,
                    actuator_ipv6,
                ))
        if not tasks:
            print("No valid sensor nodes to monitor.")
            return

        gather_task = asyncio.gather(*(asyncio.ensure_future(t) for t in tasks))
        loop = asyncio.get_running_loop()

        def _handle_sigint():
            print("\n[SHUTDOWN] Ctrl+C received, deregistering observers and exiting...")
            gather_task.cancel()

        try:
            loop.add_signal_handler(signal.SIGINT, _handle_sigint)
        except NotImplementedError:
            pass

        try:
            await gather_task
        except asyncio.CancelledError:
            pass

    finally:
        await influx_client.close()

if __name__ == "__main__":
    asyncio.run(main())

