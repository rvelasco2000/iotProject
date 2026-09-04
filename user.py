import asyncio
import json
import os
from aiocoap import *
from influxdb_client import InfluxDBClient
from dotenv import load_dotenv
def load_config(filename="config.json"):
    if not os.path.exists(filename):
        print(f"File {filename} not found")
        return []
    with open(filename,"r") as f:
        config=json.load(f)
        return config.get("patients",[]), config.get("influxdb",{})
    
async def send_coap_command(ipv6, resource, payload_val):
    protocol=await Context.create_client_context()
    uri=f"coap://[{ipv6}]/{resource}"
    payload=str(payload_val).encode("utf-8")
    request=Message(code=PUT, uri=uri, payload=payload)
    try:
        response = await asyncio.wait_for(protocol.request(request).response, timeout=5.0)
        print(f"\n[COAP] Resource'{resource}' on [{ipv6}] set to{payload_val} Status: {response.code}")
    except asyncio.TimeoutError:
        print(f"\n[COAP ERROR] Timeout occurred while contacting {uri}")
    except Exception as e:
        print(f"\n[COAP ERROR] cannot contact {uri}: {e}")

def influx_query(influx_cfg,query_type,patient_name):
    load_dotenv()
    token=os.getenv("INFLUX_TOKEN")
    client = InfluxDBClient(url=influx_cfg.get("url"), token=token, org=influx_cfg.get("org"))
    query_api=client.query_api()
    bucket_vitals=influx_cfg.get("bucket","vital_signs")
    bucket_decisions=influx_cfg.get("decision_bucket", "panic_decision")
    if query_type == "vitals":
        query = f'''
            from(bucket:"{bucket_vitals}")
            |> range(start: -15m)
            |> filter(fn: (r) => r._measurement == "patient_vitals" and r.patient_name == "{patient_name}")
        '''
        print(f"\nLast vital_signs (15 min) for {patient_name}")
    else:
        query = f'''
            from(bucket:"{bucket_decisions}")
            |> range(start: -1h)
            |> filter(fn: (r) => r._measurement == "panic_decisions" and r.patient_name == "{patient_name}")
            |> yield(name: "decisions")
        '''
        print(f"\n Last decisions(1 hour) for {patient_name}") 
    try:
        tables = query_api.query(query)
        grouped_results={}
        for table in tables:
            for record in table.records:
                local_time=record.get_time().astimezone()
                formatted_time=local_time.strftime("%d-%m-%Y %H:%M:%S")
                if (formatted_time not in grouped_results):
                    grouped_results[formatted_time] = []        
                field_name = record.get_field()
                field_value = record.get_value()
                grouped_results[formatted_time].append(f"{field_name}: {field_value}")
        for time_key, fields_list in grouped_results.items():
            fields_str = " | ".join(fields_list)
            print(f"[{time_key}] {fields_str}")    
    except Exception as e:
        print(f"Errore InfluxDB: {e}")
    finally:
        client.close()

async def main():
    patients, influx_cfg = load_config()
    if not patients:
        return
    while True:
        print("=== SELECT PATIENT NAME ===")
        for i, p in enumerate(patients):
            print(f"[{i}] {p.get('patient_name')}")
        
        user_selected=input("Select Patient: ")
        try:
            patient_selected=int(user_selected)
        except ValueError:
            print("Invalid input. Please enter a number.")
            continue
        if(patient_selected < 0 or patient_selected >= len(patients)):
            print("Invalid selection. Please try again.")
            continue
        else:
            break
    patient = patients[patient_selected]
    patient_name= patient.get("patient_name")
    
    sensor_ipv6 = patient.get("sensor_nodes", [{}])[0].get("ipv6")
    while True:
        print("1. Activate Fast Sampling Mode (5 sec) [Panic Mode]")
        print("2. Deactivate Fast Sampling Mode (Restore 30 sec)")
        print("3. Query: Last recorded vital signs (SpO2, HR, RR)")
        print("4. Query: Alarm/pump activation history (last hour)")
        print("0. Exit")
        
        choice = input("Choice: ")
        match(choice):
            case "1":
                await send_coap_command(sensor_ipv6, "vital_signs", "1")
            case "2":
                await send_coap_command(sensor_ipv6, "vital_signs", "0")
            case "3":
                influx_query(influx_cfg, "vitals", patient_name)
            case "4":
                influx_query(influx_cfg, "decisions", patient_name)
            case "0":
                return
            case _:
                print("please select a valid option")    
if __name__ == "__main__":
    asyncio.run(main())                        

