import asyncio
from aiocoap import *
import cbor2
import json
from datetime import datetime
import os

def load_configuration(filename="config.json"):
    if not os.path.exists(filename):
        raise FileNotFoundError(f"Configuration file '{filename}' not found!")
    with open(filename, "r") as f:
        return json.load(f)

async def observe_sensor(protocol, app_name, sensor_id, patient_name, ipv6):
    """Handles the CoAP Observe connection for a single patient's sensor"""
    resource_path = "vital_signs"
    uri = f"coap://[{ipv6}]/{resource_path}"
    request = Message(code=GET, uri=uri, observe=0)
    pr = protocol.request(request)

    try:
        first_response = await pr.response
        if not first_response.code.is_successful():
            print(f"[ERROR] {patient_name} (Node {sensor_id}) replied with CoAP Response: {first_response.code}")
        elif len(first_response.payload) > 0:
            reception_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cbor_data = cbor2.loads(first_response.payload)
            
            print(f"\n=== FIRST RESPONSE [{app_name}] ===")
            print(f"Patient: {patient_name} (ID: {sensor_id})")
            print(f"IPv6: {ipv6}")
            print(f"Received at: {reception_time}")
            print(json.dumps(cbor_data, indent=4))
        else:
            print(f"[WARNING] {patient_name} (Node {sensor_id}): Payload is empty.")
        async for packet in pr.observation:
            if len(packet.payload) > 0:
                reception_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cbor_data = cbor2.loads(packet.payload)
                print(f"\n=== NOTIFICATION [{app_name}] ===")
                print(f"Patient: {patient_name} (ID: {sensor_id})")
                print(f"Received at: {reception_time}")
                print(json.dumps(cbor_data, indent=4))

    except Exception as e:
        print(f"[COMMUNICATION ERROR] Patient {patient_name} (Node {sensor_id}): {e}")


async def main():
    try:
        config = load_configuration()
        app_name = config.get("applicationName", "Unknown Application")
        sensor_nodes = config.get("sensor_nodes", [])
    except Exception as e:
        print(f"Error loading the configuration file: {e}")
        return

    if not sensor_nodes:
        print("No sensor nodes configured in config.json.")
        return

    print(f"Starting '{app_name}' monitoring system...")
    print(f"Configured to monitor {len(sensor_nodes)} patient(s) concurrently.\n")
    
    protocol = await Context.create_client_context()
    tasks = [
        observe_sensor(
            protocol, 
            app_name, 
            node.get("id"), 
            node.get("patient_name"), 
            node.get("ipv6")
        )
        for node in sensor_nodes
    ]
    await asyncio.gather(*tasks)

if __name__ == "__main__":
    asyncio.run(main())
