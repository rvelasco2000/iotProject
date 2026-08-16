import asyncio
from aiocoap import *
import cbor2

async def main():
    print("Avvio client CoAP. In attesa dei dati vitali...")
    protocol = await Context.create_client_context()

    # Sostituisci l'IP se necessario (ora vedo che usi il Nodo 2)
    sensor_ip = "fd00::202:2:2:2"
    uri = f"coap://[{sensor_ip}]/vital_signs"

    request = Message(code=GET, uri=uri, observe=0)
    pr = protocol.request(request)

    try:
        # 1. Lettura del primo pacchetto
        primo_pacchetto = await pr.response
        dati_cbor = cbor2.loads(primo_pacchetto.payload)
        print(f"\n[ PRIMA RISPOSTA ] -> {dati_cbor}")

        # 2. Ciclo infinito di ascolto per l'Observe
        print("\n--- In attesa delle notifiche in tempo reale ---\n")
        async for pacchetto in pr.observation:
            dati_cbor = cbor2.loads(pacchetto.payload)
            spo2 = dati_cbor.get('s', 'N/A')
            resp = dati_cbor.get('r', 'N/A')
            hr = dati_cbor.get('h', 'N/A')
            
            print(f"[ NOTIFICA ] SpO2: {spo2}% | Respiro: {resp} bpm | Battito: {hr} bpm")

    except Exception as e:
        print(f"Errore di connessione: {e}")

if __name__ == "__main__":
    asyncio.run(main())
