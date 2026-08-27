import asyncio
from aiocoap import *
import cbor2
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from datetime import datetime
from collections import deque

from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

#this identify critical threshold for the alarm
HR_CRITICAL=100
RR_CRITICAL=24
SPO2_CRITICAL=92

#this indentify danger threshold for the activation of O2 pump
SPO2_DANGER=85
WINDOW_SIZE=5
CONFIRM_COUNT=4

class PatientState:
    def __init__(self, patient_name):
        self.patient_name = patient_name
        self.window=deque(maxlen=WINDOW_SIZE)
        self.pump_active=False
        self.alarm_active=False

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
        return "stable"
        
patient_states: dict[str, PatientState] = {}

async def send_actuator_command(protocol,patient_name,actuator_ipv6,resource,state_val):
    if(not actuator_ipv6):
        print("[ACTUATOR ERROR] no ipv6 configured for this actuator")
        return False
    uri=f"coap://[{actuator_ipv6}]/{resource}"
    payload=str(state_val).encode("utf-8")
    request=Message(code=PUT,uri=uri,payload=payload)
    try:
        response=await protocol.request(request).response
        print(f"[ACTUATOR] Resource'{resource}'on[{actuator_ipv6}] assciated to [{patient_name}] set on {state_val} -> Coap response: {response.code}")
        return response.code.is_successful()
    except Exception as e:
        print(f"[ACTUATOR COMMUNICATION ERROR] cannot contact {uri}: {e}")
        return False
    
async def write_decision_event(write_api, bucket, org, patient_name, decision, hr, rr, spo2):
    point = (
        Point("panic_decisions")
        .tag("patient_name", patient_name)
        .field("decision", decision)
        .field("heart_rate", int(hr))
        .field("respiration_rate", int(rr))
        .field("spo2", int(spo2))
    )
    try:
        await write_api.write(bucket=bucket, org=org, record=point)
    except Exception as e:
        print(f"[INFLUXDB ERROR] Failed to write decision event for {patient_name}: {e}") 

async def evaluate_and_act(protocol,state,sensor_id,hr,rr,spo2,write_api,bucket,org,actuator_ipv6=None):
    state.add_reading(hr,rr,spo2)
    decision=state.evaluate_patient_condition()
    match decision:
        case "activate_pump":
            if(not state.pump_active):
                state.pump_active=True
                state.alarm_active=True
                await send_actuator_command(protocol,state.patient_name,actuator_ipv6, "pump", "1")
                await send_actuator_command(protocol,state.patient_name,actuator_ipv6, "alarm", "1")
        case "activate_alarm":
            if(not state.alarm_active):
                state.alarm_active=True
                await send_actuator_command(protocol,state.patient_name,actuator_ipv6, "alarm", "1")
        case "stable":
            if(state.alarm_active):
                await send_actuator_command(protocol,state.patient_name,actuator_ipv6, "alarm", "0")
                if(state.pump_active):
                    await send_actuator_command(protocol,state.patient_name,actuator_ipv6, "pump", "0")
                    state.pump_active=False
                state.alarm_active=False
        case "insufficient_data":
            print("data is not sufficient")        
        case _:
            print("Unknown decision")   
    if decision not in ("insufficient_data", "stable"):
        await write_decision_event(write_api,bucket, org, state.patient_name, decision, hr, rr, spo2)
    return decision     
       
def load_configuration(filename="config.json"):
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Configuration file '{filename}' not found!")
    with open(filename, "r") as f:
        return json.load(f)

async def write_to_influx(write_api, bucket, org, patient_name, cbor_data, reception_time):
    try:
        events = cbor_data.get('e', [])
        point = Point("patient_vitals") \
            .tag("patient_name", patient_name) \
            .tag("sensor_bn", str(cbor_data.get('bn', 'unknown'))) \
            .tag("timestamp", reception_time)
            
        has_data = False
        for event in events:
            name = event.get('n')
            value = event.get('v')
            
            if name == "spo2":
                point.field("spo2", int(value))
                has_data = True
            elif name == "resRate":
                point.field("respiration_rate", int(value))
                has_data = True
            elif name == "heartRate":
                point.field("heart_rate", int(value))
                has_data = True

        if has_data:
            await write_api.write(bucket=bucket, org=org, record=point)
            
    except Exception as e:
        print(f"[INFLUXDB ERROR] Failed to write data for {patient_name}: {e}")

def extract_vitals(cbor_data):
    values={}
    events=cbor_data.get("e",[])
    for event in events:
        name = event.get('n')
        value = event.get('v')
        if name == "heartRate":
            values["hr"] = value
        elif name == "resRate":
            values["rr"] = value
        elif name == "spo2":
            values["spo2"] = value
    if {"hr", "rr", "spo2"} <= values.keys():
        return values["hr"], values["rr"], values["spo2"]
    return None

async def observe_sensor(protocol, app_name, sensor_id, patient_name, ipv6, write_api, influx_bucket, influx_org,decision_bucket,actuator_ipv6=None):
    resource_path = "vital_signs"
    uri = f"coap://[{ipv6}]/{resource_path}"
    state=patient_states.setdefault(patient_name, PatientState(patient_name))
    request = Message(code=GET, uri=uri, observe=0)
    pr = protocol.request(request)

    async def handle_packet(payload,label):
        if (len(payload)==0):
            return;
        timezone_italy = ZoneInfo("Europe/Rome")
        reception_time = datetime.now(timezone_italy).strftime("%d-%m-%Y %H:%M:%S")
        cbor_data = cbor2.loads(payload)
        print(f"\n=== {label} [{app_name}] ===")
        print(f"Patient: {patient_name} (ID: {sensor_id}) | Received at: {reception_time}")
        print(f"Decoded CBOR: {json.dumps(cbor_data, indent=2)}")
        await write_to_influx(write_api, influx_bucket, influx_org, patient_name, cbor_data, reception_time)
        vitals=extract_vitals(cbor_data)
        if(vitals is not None):
            hh,rr,spo2=vitals
            decision = await evaluate_and_act(protocol, state, sensor_id, hh, rr, spo2,write_api, decision_bucket, influx_org,actuator_ipv6)
            print(f"[DECISION] {patient_name}: {decision}")
    try:
        first_response = await pr.response
        
        if not first_response.code.is_successful():
            print(f"[ERROR] {patient_name} (Node {sensor_id}) replied with CoAP Response: {first_response.code}")
        else:
            await handle_packet(first_response.payload,"FIRST RESPONSE")

        async for packet in pr.observation:
            await handle_packet(packet.payload,"NOTIFICATION")
    except Exception as e:
        print(f"[COMMUNICATION ERROR] Patient {patient_name} (Node {sensor_id}): {e}")

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
    decisions_bucket=influx_cfg.get("decision_bucket")

    print(f"Starting '{app_name}' monitoring system...")
    print(f"Connected to InfluxDB at {influx_cfg.get('url')}")
    print(f"Configured to monitor {len(patients_cfg)} patient(s) concurrently.\n")
    
    protocol = await Context.create_client_context()

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
                    influx_cfg.get("bucket"),
                    influx_cfg.get("org"),
                    decisions_bucket,
                    actuator_ipv6,
                ))
            if not tasks:
                print("No valid sensor nodes to monitor.")
                return
            await asyncio.gather(*tasks)
        
    finally:
        await influx_client.close()

if __name__ == "__main__":
    asyncio.run(main())


