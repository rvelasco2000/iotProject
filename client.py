import asyncio
from aiocoap import *
import cbor2
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from datetime import datetime

from influxdb_client import Point
from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync

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
            
            # ATTENZIONE: Mantenuto float() per evitare crash con eventuali valori decimali
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

async def observe_sensor(protocol, app_name, sensor_id, patient_name, ipv6, write_api, influx_bucket, influx_org):
    resource_path = "vital_signs"
    uri = f"coap://[{ipv6}]/{resource_path}"
    
    request = Message(code=GET, uri=uri, observe=0)
    pr = protocol.request(request)

    try:
        first_response = await pr.response
        
        if not first_response.code.is_successful():
            print(f"[ERROR] {patient_name} (Node {sensor_id}) replied with CoAP Response: {first_response.code}")
        elif len(first_response.payload) > 0:
            timezone_italy = ZoneInfo("Europe/Rome")
            reception_time = datetime.now(timezone_italy).strftime("%d-%m-%Y %H:%M:%S")
            cbor_data = cbor2.loads(first_response.payload)
            
            print(f"\n=== FIRST RESPONSE [{app_name}] ===")
            print(f"Patient: {patient_name} (ID: {sensor_id}) | Received at: {reception_time}")
            # --- STAMPA DEL CONTENUTO CBOR AGGIUNTA QUI ---
            print(f"Decoded CBOR: {json.dumps(cbor_data, indent=2)}")
            
            await write_to_influx(write_api, influx_bucket, influx_org, patient_name, cbor_data, reception_time)

        async for packet in pr.observation:
            if len(packet.payload) > 0:
                timezone_italy = ZoneInfo("Europe/Rome")
                reception_time = datetime.now(timezone_italy).strftime("%d-%m-%Y %H:%M:%S")
                cbor_data = cbor2.loads(packet.payload)
                
                print(f"\n=== NOTIFICATION [{app_name}] ===")
                print(f"Patient: {patient_name} (ID: {sensor_id}) | Received at: {reception_time}")
                # --- STAMPA DEL CONTENUTO CBOR AGGIUNTA QUI ---
                print(f"Decoded CBOR: {json.dumps(cbor_data, indent=2)}")
            
                await write_to_influx(write_api, influx_bucket, influx_org, patient_name, cbor_data, reception_time)

    except Exception as e:
        print(f"[COMMUNICATION ERROR] Patient {patient_name} (Node {sensor_id}): {e}")

async def main():
    try:
        config = load_configuration()
        app_name = config.get("applicationName", "Unknown Application")
        sensor_nodes = config.get("sensor_nodes", [])
        influx_cfg = config.get("influxdb", {})
    except Exception as e:
        print(f"Error loading the configuration file: {e}")
        return

    if not sensor_nodes:
        print("No sensor nodes configured in config.json.")
        return
        
    load_dotenv()
    
    influx_client = InfluxDBClientAsync(
        url=influx_cfg.get("url"),
        token=os.getenv("INFLUX_TOKEN"),
        org=influx_cfg.get("org")
    )
    write_api = influx_client.write_api()

    print(f"Starting '{app_name}' monitoring system...")
    print(f"Connected to InfluxDB at {influx_cfg.get('url')}")
    print(f"Configured to monitor {len(sensor_nodes)} patient(s) concurrently.\n")
    
    protocol = await Context.create_client_context()

    try:
        tasks = [
            observe_sensor(
                protocol, 
                app_name, 
                node.get("id"), 
                node.get("patient_name"), 
                node.get("ipv6"),
                write_api,
                influx_cfg.get("bucket"),
                influx_cfg.get("org")
            )
            for node in sensor_nodes
        ]
        
        await asyncio.gather(*tasks)
        
    finally:
        await influx_client.close()

if __name__ == "__main__":
    asyncio.run(main())

