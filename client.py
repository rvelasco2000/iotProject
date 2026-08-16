import asyncio
from aiocoap import *
import cbor2
import json

async def main():
    print("Avvio client CoAP. In attesa dei dati vitali...")
    protocol = await Context.create_client_context()

    # Assicurati che l'IP sia quello del tuo sensore attuale
    sensor_ip = "fd00::202:2:2:2"
    uri = f"coap://[{sensor_ip}]/vital_signs"

    # Richiesta Observe
    request = Message(code=GET, uri=uri, observe=0)
    pr = protocol.request(request)

    try:
        # 1. Lettura del primo pacchetto
        primo_pacchetto = await pr.response
        dati_cbor = cbor2.loads(primo_pacchetto.payload)
        
        print("\n[ PRIMA RISPOSTA ] - Informazioni complete:")
        # json.dumps con indent=4 stampa il dizionario in modo molto leggibile
        print(json.dumps(dati_cbor, indent=4))

        # 2. Ciclo infinito di ascolto per le notifiche
        print("\n--- In attesa delle notifiche in tempo reale ---\n")
        async for pacchetto in pr.observation:
            dati_cbor = cbor2.loads(pacchetto.payload)
            
            print("\n[ NOTIFICA RICEVUTA ]")
            print(json.dumps(dati_cbor, indent=4))

    except Exception as e:
        print(f"Errore di connessione o decodifica: {e}")

if __name__ == "__main__":
    asyncio.run(main())
